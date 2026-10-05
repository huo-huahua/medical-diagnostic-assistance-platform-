"""Prediction orchestration: inference + explanation + optional narrative."""

from __future__ import annotations

import time
from typing import Any

import numpy as np
from sqlalchemy.orm import Session

from app.core.config import REPO_ROOT, settings
from app.core.errors import FeatureCountError, ValidationError
from app.core.logging import get_logger
from app.db.models import PredictionRecord, User
from app.ml.registry import confidence_band, get_registry
from app.services.explainer import compute_contributions
from app.services.llm_gateway import get_gateway

logger = get_logger(__name__)

_background_cache: dict[str, np.ndarray] = {}


def _background_for(disease: str, n_features: int) -> np.ndarray:
    """Reuse the training features as the SHAP background distribution."""
    if disease in _background_cache:
        return _background_cache[disease]

    import pandas as pd

    raw_name = {"breast": "wdbc_raw.csv", "heart": "heart_features.csv"}[disease]
    path = REPO_ROOT / "ml" / "data" / "raw" / raw_name
    frame = pd.read_csv(path)
    if "Diagnosis" in frame.columns:
        frame = frame.drop(columns=["Diagnosis"])
    frame = frame.replace("?", np.nan).apply(lambda c: pd.to_numeric(c, errors="coerce"))
    frame = frame.fillna(frame.median(numeric_only=True))
    arr = frame.to_numpy(dtype=float)[:200]
    _background_cache[disease] = arr
    return arr


def _narrative_prompt(disease: str, verdict_label: str, prob: float,
                      contributions: list[dict]) -> tuple[str, str]:
    top = contributions[:6]
    lines = "\n".join(
        f"- {c['name_zh']}（{c['name_en']}）当前值 {c['value']:.4f}，"
        f"贡献 {c['contribution']:+.4f}"
        for c in top
    )
    disease_zh = "乳腺癌" if disease == "breast" else "心脏病"
    system = (
        f"你是一位临床决策支持系统的解释模块，负责{disease_zh}风险模型结果的通俗解读。"
        "要求：用简体中文，语气专业、克制、易读；使用短段落；"
        "严禁使用「确诊」「一定」「保证」等绝对化表述；"
        "严禁给出药物名称或剂量；必须提醒最终诊断以执业医师为准。"
    )
    user = (
        f"模型判定：{verdict_label}\n"
        f"阳性概率（校准后）：{prob:.2%}\n"
        f"贡献度最高的特征：\n{lines}\n\n"
        "请写一段 120-180 字的解读，覆盖三点：\n"
        "1) 哪些指标对本次结果影响最大；\n"
        "2) 这个结果应当如何理解（强调这是统计风险而非临床诊断）；\n"
        "3) 一条具体的后续建议。\n"
        "直接输出正文，不要标题，不要复述问题。"
    )
    return system, user


def run_prediction(
    *,
    db: Session | None,
    user: User | None,
    disease: str,
    algo: str | None,
    features: list[float],
    case_label: str | None = None,
    persist: bool = True,
    with_explanation: bool = True,
    with_narrative: bool = False,
) -> dict[str, Any]:
    started = time.perf_counter()
    registry = get_registry()
    mod = registry.disease_info(disease)
    expected = mod["n_features"]

    if len(features) != expected:
        raise FeatureCountError(
            f"{disease} expects {expected} features, received {len(features)}"
        )

    for i, value in enumerate(features):
        if not np.isfinite(value):
            key = mod["feature_keys"][i]
            raise ValidationError(f"Feature '{key}' is not a finite number")

    model, raw_vec, positive_prob = registry.predict(disease, algo, features)

    # Optional soft range check — warns rather than blocks, since real
    # measurements can legitimately fall outside the training envelope.
    range_warnings = []
    stats = mod.get("feature_stats", {})
    for key, value in zip(mod["feature_keys"], features):
        s = stats.get(key)
        if not s:
            continue
        span = max(s["max"] - s["min"], 1e-9)
        if value < s["min"] - 0.25 * span or value > s["max"] + 0.25 * span:
            range_warnings.append(key)

    band = confidence_band(positive_prob, model.threshold)
    is_positive = positive_prob >= model.threshold
    verdict = "positive" if is_positive else "negative"
    verdict_label = (
        mod["positive_label_zh"] if is_positive else mod["negative_label_zh"]
    )

    explanation = None
    contributions: list[dict] = []
    if with_explanation:
        background = _background_for(disease, expected)
        values, base = compute_contributions(model, model.info["algorithm"],
                                             raw_vec, background)
        schema = {f["key"]: f for f in mod["feature_schema"]}
        for key, val, contrib in zip(mod["feature_keys"], features, values):
            spec = schema.get(key, {})
            c = float(contrib)
            contributions.append({
                "key": key,
                "name_zh": spec.get("name_zh", key),
                "name_en": spec.get("name_en", key),
                "group": spec.get("group", "default"),
                "value": float(val),
                "contribution": round(c, 6),
                "direction": (
                    "positive" if c > 1e-9 else ("negative" if c < -1e-9 else "neutral")
                ),
            })
        contributions.sort(key=lambda x: abs(x["contribution"]), reverse=True)
        explanation = {
            "base_value": round(float(base), 6),
            "contributions": contributions,
            "top_positive": [c for c in contributions if c["contribution"] > 0][:5],
            "top_negative": [c for c in contributions if c["contribution"] < 0][:5],
            "method": "shap.TreeExplainer" if model.info["algorithm"] != "lr"
                      else "shap.LinearExplainer",
        }

    narrative = None
    narrative_source = None
    llm_meta = {"llm_used": False, "cache_hit": False}

    if with_narrative and settings.enable_rag_llm:
        system, prompt = _narrative_prompt(disease, verdict_label, positive_prob,
                                           contributions)
        gateway = get_gateway()
        text, llm_meta = gateway.complete(
            purpose="explain",
            system=system,
            user=prompt,
            # Cache on the model verdict + rounded probabilities + top features,
            # so near-identical inputs reuse the same paid response.
            cache_payload=(
                f"{model.info['id']}|{verdict}|{round(positive_prob, 3)}|"
                + "|".join(f"{c['key']}:{round(c['contribution'], 3)}"
                           for c in contributions[:6])
            ),
            temperature=0.3,
        )
        if text:
            narrative = text
            narrative_source = (
                "cache" if llm_meta.get("cache_hit") else "llm"
            )
        else:
            narrative = _template_narrative(disease, verdict_label,
                                            positive_prob, contributions)
            narrative_source = "template"

    elapsed_ms = int((time.perf_counter() - started) * 1000)

    record_id = None
    if persist and db is not None and user is not None:
        record = PredictionRecord(
            user_id=user.id,
            case_label=case_label,
            disease=disease,
            model_id=model.info["id"],
            features={k: float(v) for k, v in zip(mod["feature_keys"], features)},
            positive_prob=round(positive_prob, 6),
            negative_prob=round(1.0 - positive_prob, 6),
            verdict=verdict,
            threshold=model.threshold,
            confidence_band=band,
            contributions=contributions or None,
            llm_used=bool(llm_meta.get("llm_used")),
            elapsed_ms=elapsed_ms,
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        record_id = record.id

    return {
        "record_id": record_id,
        "disease": disease,
        "model_id": model.info["id"],
        "algorithm": model.info["algorithm"],
        "algorithm_zh": model.info["algorithm_zh"],
        "verdict": verdict,
        "verdict_label": verdict_label,
        "positive_prob": round(positive_prob, 6),
        "negative_prob": round(1.0 - positive_prob, 6),
        "threshold": model.threshold,
        "confidence_band": band,
        "metrics": model.info["test"],
        "explanation": explanation,
        "narrative": narrative,
        "narrative_source": narrative_source,
        "elapsed_ms": elapsed_ms,
        "range_warnings": range_warnings,
        "llm_cache_hit": bool(llm_meta.get("cache_hit")),
    }


def _template_narrative(disease: str, verdict_label: str, prob: float,
                        contributions: list[dict]) -> str:
    """Deterministic fallback so the UI is never empty when the LLM is off."""
    disease_zh = "乳腺癌" if disease == "breast" else "心脏病"
    top = contributions[:3]
    if top:
        items = "、".join(
            f"{c['name_zh']}（{'↑' if c['contribution'] > 0 else '↓'}）" for c in top
        )
        influence = f"对本次结果影响最大的指标依次为 {items}。"
    else:
        influence = "本次未计算特征贡献。"

    return (
        f"模型对{disease_zh}的评估结果为「{verdict_label}」，"
        f"阳性概率约 {prob:.1%}。{influence}"
        "需要注意，这是基于公开数据集训练出的统计风险估计，"
        "反映的是群体规律而非个体结论，不能作为临床诊断依据。"
        "建议携带完整检查报告前往正规医院专科门诊，由执业医师结合"
        "病史、体征与影像学证据综合判断。"
    )
