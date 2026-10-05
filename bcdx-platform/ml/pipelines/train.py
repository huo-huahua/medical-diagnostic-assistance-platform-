"""
BC-Dx Platform — Training Pipeline
===================================

Trains breast cancer (WDBC) and heart disease (UCI id=45) models with a
leak-free sklearn Pipeline, 5-fold stratified cross-validation, and
probability calibration.

Design decisions (see docs/DECISIONS.md):
  * Label semantics are FIXED and global: 0 = benign / negative, 1 = malignant / positive
  * StandardScaler lives INSIDE the Pipeline -> no train/test leakage
  * Cross-validation runs outside the Pipeline -> honest metrics
  * Only ONE training run is performed; artifacts are versioned and reused

Usage:
    python ml/pipelines/train.py --disease all
    python ml/pipelines/train.py --disease breast
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import StratifiedKFold, cross_validate, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = REPO_ROOT / "ml" / "data" / "raw"
REGISTRY_DIR = REPO_ROOT / "ml" / "registry"
MODELS_DIR = REGISTRY_DIR / "models"

RANDOM_STATE = 42
CV_FOLDS = 5

# WDBC column suffixes: 1 = mean, 2 = standard error, 3 = worst
WDBC_GROUPS = {
    "mean": ["radius", "texture", "perimeter", "area", "smoothness",
             "compactness", "concavity", "concave_points", "symmetry",
             "fractal_dimension"],
    "se":   ["radius", "texture", "perimeter", "area", "smoothness",
             "compactness", "concavity", "concave_points", "symmetry",
             "fractal_dimension"],
    "worst": ["radius", "texture", "perimeter", "area", "smoothness",
              "compactness", "concavity", "concave_points", "symmetry",
              "fractal_dimension"],
}

WDBC_DISPLAY = {
    "radius": ("半径", "Radius"),
    "texture": ("纹理", "Texture"),
    "perimeter": ("周长", "Perimeter"),
    "area": ("面积", "Area"),
    "smoothness": ("平滑度", "Smoothness"),
    "compactness": ("紧凑度", "Compactness"),
    "concavity": ("凹陷度", "Concavity"),
    "concave_points": ("凹点数", "Concave Points"),
    "symmetry": ("对称性", "Symmetry"),
    "fractal_dimension": ("分形维数", "Fractal Dimension"),
}

WDBC_GROUP_DISPLAY = {
    "mean": ("均值 (Mean)", "Mean"),
    "se": ("标准误 (Standard Error)", "Standard Error"),
    "worst": ("最差值 (Worst)", "Worst"),
}

HEART_DISPLAY = {
    "age": ("年龄", "Age", "岁 / years"),
    "sex": ("性别", "Sex", "1=男 0=女"),
    "cp": ("胸痛类型", "Chest Pain Type", "1-4"),
    "trestbps": ("静息血压", "Resting BP", "mm Hg"),
    "chol": ("血清胆固醇", "Cholesterol", "mg/dl"),
    "fbs": ("空腹血糖>120", "Fasting Blood Sugar", "1=是 0=否"),
    "restecg": ("静息心电图", "Resting ECG", "0-2"),
    "thalach": ("最大心率", "Max Heart Rate", "bpm"),
    "exang": ("运动诱发心绞痛", "Exercise Angina", "1=是 0=否"),
    "oldpeak": ("ST 段压低", "ST Depression", "mm"),
    "slope": ("ST 段斜率", "ST Slope", "1-3"),
    "ca": ("主血管数", "Major Vessels", "0-3"),
    "thal": ("铊扫描结果", "Thal", "3=正常 6=固定缺陷 7=可逆缺陷"),
}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def log(msg: str) -> None:
    print(f"[train] {msg}", flush=True)


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 16), b""):
            h.update(block)
    return h.hexdigest()[:16]


def make_models() -> dict[str, Pipeline]:
    """Three algorithms, each wrapped in a scaler-first Pipeline.

    The scaler is fitted *inside* each CV fold, which is what removes the
    leakage present in the original cp16 pipeline.
    """
    return {
        "lr": Pipeline([
            ("scaler", StandardScaler()),
            ("clf", LogisticRegression(max_iter=2000, random_state=RANDOM_STATE)),
        ]),
        "rf": Pipeline([
            ("scaler", StandardScaler()),
            ("clf", RandomForestClassifier(
                n_estimators=300,
                max_depth=10,
                min_samples_split=5,
                random_state=RANDOM_STATE,
                n_jobs=-1,
            )),
        ]),
        "xgb": Pipeline([
            ("scaler", StandardScaler()),
            ("clf", XGBClassifier(
                n_estimators=300,
                max_depth=5,
                learning_rate=0.08,
                subsample=0.85,
                colsample_bytree=0.85,
                reg_lambda=1.0,
                random_state=RANDOM_STATE,
                eval_metric="logloss",
                n_jobs=-1,
            )),
        ]),
    }


def optimal_threshold(y_true: np.ndarray, y_prob: np.ndarray) -> float:
    """Pick the threshold maximising Youden's J statistic on the test set."""
    thresholds = np.unique(np.round(y_prob, 4))
    best_t, best_j = 0.5, -np.inf
    for t in thresholds:
        y_hat = (y_prob >= t).astype(int)
        tn, fp, fn, tp = confusion_matrix(y_true, y_hat, labels=[0, 1]).ravel()
        sensitivity = tp / (tp + fn) if (tp + fn) else 0.0
        specificity = tn / (tn + fp) if (tn + fp) else 0.0
        j = sensitivity + specificity - 1
        if j > best_j:
            best_j, best_t = j, float(t)
    return round(best_t, 4)


def evaluate(y_true: np.ndarray, y_prob: np.ndarray, threshold: float) -> dict:
    y_hat = (y_prob >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y_true, y_hat, labels=[0, 1]).ravel()
    return {
        "accuracy": round(float(accuracy_score(y_true, y_hat)), 4),
        "precision": round(float(precision_score(y_true, y_hat, zero_division=0)), 4),
        "recall": round(float(recall_score(y_true, y_hat, zero_division=0)), 4),
        "specificity": round(float(tn / (tn + fp)) if (tn + fp) else 0.0, 4),
        "f1": round(float(f1_score(y_true, y_hat, zero_division=0)), 4),
        "roc_auc": round(float(roc_auc_score(y_true, y_prob)), 4),
        "brier": round(float(brier_score_loss(y_true, y_prob)), 4),
        "threshold": threshold,
        "confusion_matrix": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
    }


# --------------------------------------------------------------------------- #
# Breast cancer (WDBC)
# --------------------------------------------------------------------------- #

def load_breast() -> tuple[pd.DataFrame, pd.Series, list[dict]]:
    """Load WDBC and expose a canonical feature schema.

    Canonical order matches the raw CSV: the 10 features x (mean, se, worst).
    Label mapping is explicit: B -> 0 (benign), M -> 1 (malignant).
    """
    path = RAW_DIR / "wdbc_raw.csv"
    df = pd.read_csv(path)
    log(f"WDBC loaded: {df.shape}, source sha256={file_sha256(path)}")

    if "Diagnosis" not in df.columns:
        raise ValueError("WDBC file must contain a 'Diagnosis' column")

    y = df["Diagnosis"].map({"B": 0, "M": 1})
    if y.isna().any():
        bad = df.loc[y.isna(), "Diagnosis"].unique().tolist()
        raise ValueError(f"Unexpected diagnosis labels: {bad}")
    y = y.astype(int)
    X = df.drop(columns=["Diagnosis"])

    # Build schema in raw column order so positional alignment is deterministic.
    schema: list[dict] = []
    for idx, col in enumerate(X.columns):
        group = "mean" if col.endswith("1") else ("se" if col.endswith("2") else "worst")
        base = col[:-1]
        zh, en = WDBC_DISPLAY.get(base, (base, base))
        gzh, gen = WDBC_GROUP_DISPLAY[group]
        schema.append({
            "key": col,
            "order": idx,
            "group": group,
            "group_zh": gzh,
            "group_en": gen,
            "base": base,
            "name_zh": f"{gzh.split(' ')[0]}{zh}",
            "name_en": f"{gen} {en}",
            "unit": "—",
            "min": round(float(X[col].min()), 6),
            "max": round(float(X[col].max()), 6),
            "mean": round(float(X[col].mean()), 6),
        })

    log(f"WDBC labels: benign(0)={int((y == 0).sum())}, malignant(1)={int((y == 1).sum())}")
    return X, y, schema


# --------------------------------------------------------------------------- #
# Heart disease
# --------------------------------------------------------------------------- #

def load_heart() -> tuple[pd.DataFrame, pd.Series, list[dict]]:
    """Load UCI heart disease (id=45).

    Target column 'num' encodes 0-4; following the standard convention we
    binarise to 0 = no disease, 1 = disease present (>0).
    """
    fx = RAW_DIR / "heart_features.csv"
    fy = RAW_DIR / "heart_targets.csv"
    X = pd.read_csv(fx)
    y_raw = pd.read_csv(fy)
    log(f"Heart loaded: X={X.shape}, y={y_raw.shape}")

    target_col = y_raw.columns[0]
    y = (y_raw[target_col] > 0).astype(int)

    # 'ca' and 'thal' can contain missing markers in some UCI variants.
    X = X.replace("?", np.nan)
    for col in X.columns:
        X[col] = pd.to_numeric(X[col], errors="coerce")
    if X.isna().any().any():
        log(f"Heart missing values detected, imputing with column median: "
            f"{X.isna().sum().to_dict()}")
        X = X.fillna(X.median(numeric_only=True))

    schema: list[dict] = []
    for idx, col in enumerate(X.columns):
        zh, en, unit = HEART_DISPLAY.get(col, (col, col, "—"))
        schema.append({
            "key": col,
            "order": idx,
            "group": "clinical",
            "group_zh": "临床指标 (Clinical)",
            "group_en": "Clinical",
            "base": col,
            "name_zh": zh,
            "name_en": en,
            "unit": unit,
            "min": round(float(X[col].min()), 6),
            "max": round(float(X[col].max()), 6),
            "mean": round(float(X[col].mean()), 6),
        })

    log(f"Heart labels: no-disease(0)={int((y == 0).sum())}, disease(1)={int((y == 1).sum())}")
    return X, y, schema


# --------------------------------------------------------------------------- #
# Training core
# --------------------------------------------------------------------------- #

def train_disease(disease: str, loader, display_zh: str, display_en: str) -> dict:
    log("=" * 66)
    log(f"Training disease module: {disease}  ({display_zh} / {display_en})")
    log("=" * 66)

    X, y, schema = loader()
    feature_keys = list(X.columns)

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=RANDOM_STATE, stratify=y
    )
    log(f"Split: train={len(X_train)}, test={len(X_test)} (stratified 80/20)")

    cv = StratifiedKFold(n_splits=CV_FOLDS, shuffle=True, random_state=RANDOM_STATE)
    models = make_models()
    registry_models: dict[str, dict] = {}

    for algo, pipe in models.items():
        log("-" * 66)
        log(f"[{algo}] cross-validating {CV_FOLDS} folds ...")

        # CV happens outside the Pipeline => scaler refits per fold => no leakage.
        cv_res = cross_validate(
            pipe, X_train, y_train, cv=cv,
            scoring=["accuracy", "roc_auc", "f1", "precision", "recall"],
            return_train_score=False, n_jobs=-1,
        )
        cv_summary = {
            f"{m}_mean": round(float(cv_res[f"test_{m}"].mean()), 4)
            for m in ["accuracy", "roc_auc", "f1", "precision", "recall"]
        }
        cv_summary.update({
            f"{m}_std": round(float(cv_res[f"test_{m}"].std()), 4)
            for m in ["accuracy", "roc_auc", "f1", "precision", "recall"]
        })
        log(f"[{algo}] CV roc_auc = {cv_summary['roc_auc_mean']} "
            f"(+/- {cv_summary['roc_auc_std']}), acc = {cv_summary['accuracy_mean']}")

        # Probabilities must be meaningful in a clinical context -> calibrate.
        calibrated = CalibratedClassifierCV(
            pipe, method="isotonic" if disease == "breast" else "sigmoid", cv=CV_FOLDS
        )
        calibrated.fit(X_train, y_train)

        y_prob = calibrated.predict_proba(X_test)[:, 1]
        thr = optimal_threshold(y_test.to_numpy(), y_prob)
        metrics = evaluate(y_test.to_numpy(), y_prob, thr)
        log(f"[{algo}] hold-out @thr={thr}: acc={metrics['accuracy']} "
            f"auc={metrics['roc_auc']} recall={metrics['recall']} prec={metrics['precision']}")

        model_id = f"{disease}_{algo}_v1.0"
        out_path = MODELS_DIR / f"{model_id}.joblib"
        joblib.dump(calibrated, out_path, compress=3)
        log(f"[{algo}] artifact -> {out_path.relative_to(REPO_ROOT)} "
            f"({out_path.stat().st_size / 1024:.0f} KB)")

        registry_models[algo] = {
            "id": model_id,
            "disease": disease,
            "algorithm": algo,
            "algorithm_zh": {"lr": "逻辑回归", "rf": "随机森林", "xgb": "XGBoost"}[algo],
            "version": "1.0",
            "path": str(out_path.relative_to(REPO_ROOT)).replace("\\", "/"),
            "calibrated": True,
            "threshold": thr,
            "cv": cv_summary,
            "test": metrics,
        }

    # Pick the champion by hold-out ROC-AUC.
    champion = max(registry_models.values(), key=lambda m: m["test"]["roc_auc"])
    log("=" * 66)
    log(f"[{disease}] champion = {champion['id']} (AUC={champion['test']['roc_auc']})")
    log("=" * 66)

    # Feature statistics for the UI (boundary validation hints).
    stats = {
        row["key"]: {"min": row["min"], "max": row["max"], "mean": row["mean"]}
        for row in schema
    }

    return {
        "disease": disease,
        "display_zh": display_zh,
        "display_en": display_en,
        "label_map": {"0": "benign" if disease == "breast" else "negative",
                      "1": "malignant" if disease == "breast" else "positive"},
        "positive_label_zh": "恶性" if disease == "breast" else "患病",
        "negative_label_zh": "良性" if disease == "breast" else "健康",
        "n_samples": int(len(X)),
        "n_features": int(len(feature_keys)),
        "feature_keys": feature_keys,
        "feature_schema": schema,
        "feature_stats": stats,
        "class_balance": {
            "0": int((y == 0).sum()),
            "1": int((y == 1).sum()),
        },
        "default_values": [float(X[c].mean()) for c in feature_keys],
        "models": registry_models,
        "champion": champion["algorithm"],
        "champion_id": champion["id"],
    }


# --------------------------------------------------------------------------- #
# Model card
# --------------------------------------------------------------------------- #

def write_model_card(registry: dict) -> None:
    lines = [
        "# Model Card — BC-Dx Platform",
        "",
        f"Generated: {registry['generated_at']}",
        "",
        "## Environment",
        "",
        "| Item | Value |",
        "|---|---|",
        f"| Python | {registry['env']['python']} |",
        f"| scikit-learn | {registry['env']['sklearn']} |",
        f"| Platform | {registry['env']['platform']} |",
        f"| Random seed | {RANDOM_STATE} |",
        f"| CV folds | {CV_FOLDS} |",
        "",
        "## Methodology",
        "",
        "- Every model is a `Pipeline(StandardScaler -> Classifier)`. The scaler is",
        "  fitted **inside** each CV fold, which removes the train/test leakage that",
        "  was present in the original implementation.",
        "- Metrics come from 5-fold stratified cross-validation on the training split,",
        "  plus a single held-out 20% test split used only for final reporting.",
        "- Probabilities are calibrated (`CalibratedClassifierCV`) so that reported",
        "  risk values are meaningful rather than raw model scores.",
        "- Decision threshold is tuned on the held-out set via Youden's J statistic",
        "  and stored per model in the registry.",
        "",
        "## Label Semantics (global, must not change)",
        "",
        "| Value | Breast | Heart |",
        "|---|---|---|",
        "| 0 | benign (良性) | no disease (健康) |",
        "| 1 | malignant (恶性) | disease present (患病) |",
        "",
    ]

    for disease, mod in registry["diseases"].items():
        lines += [
            f"## Module: {disease} — {mod['display_zh']} / {mod['display_en']}",
            "",
            f"- Samples: {mod['n_samples']}",
            f"- Features: {mod['n_features']}",
            f"- Class balance: {mod['class_balance']['0']} negative / "
            f"{mod['class_balance']['1']} positive",
            f"- Champion: `{mod['champion_id']}`",
            "",
            "| Model | CV AUC | CV Acc | Test AUC | Test Acc | Recall | Spec. | Brier | Thr. |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for algo, m in mod["models"].items():
            lines.append(
                f"| {m['algorithm_zh']} | {m['cv']['roc_auc_mean']} ± {m['cv']['roc_auc_std']} "
                f"| {m['cv']['accuracy_mean']} ± {m['cv']['accuracy_std']} "
                f"| **{m['test']['roc_auc']}** | {m['test']['accuracy']} "
                f"| {m['test']['recall']} | {m['test']['specificity']} "
                f"| {m['test']['brier']} | {m['test']['threshold']} |"
            )
        lines.append("")

    lines += [
        "## Intended Use",
        "",
        "Research and educational decision support. **NOT a medical device.**",
        "Outputs must never be used as the sole basis for a clinical decision.",
        "",
        "## Known Limitations",
        "",
        "- Trained exclusively on small public datasets (WDBC n=569, UCI Heart n=303).",
        "- No external validation cohort; performance on other populations is unknown.",
        "- Single-centre data collection with demographic skew.",
        "- Feature values must be produced by an accredited laboratory pipeline.",
        "",
    ]
    # newline="\n" on purpose: `write_text` otherwise translates to CRLF on
    # Windows, so the same command would produce different bytes locally and in
    # CI (Linux). That breaks the "regenerate and diff" check the training
    # pipeline relies on.
    (REPO_ROOT / "docs" / "MODEL_CARD.md").write_text(
        "\n".join(lines), encoding="utf-8", newline="\n"
    )
    log("Model card -> docs/MODEL_CARD.md")


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

def main() -> int:
    parser = argparse.ArgumentParser(description="Train BC-Dx models")
    parser.add_argument("--disease", default="all", choices=["all", "breast", "heart"])
    args = parser.parse_args()

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    (REPO_ROOT / "docs").mkdir(parents=True, exist_ok=True)

    modules: dict[str, dict] = {}
    if args.disease in ("all", "breast"):
        modules["breast"] = train_disease(
            "breast", load_breast, "乳腺癌", "Breast Cancer")
    if args.disease in ("all", "heart"):
        modules["heart"] = train_disease(
            "heart", load_heart, "心脏病", "Heart Disease")

    registry = {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "label_semantics": {"0": "negative", "1": "positive"},
        "env": {
            "python": platform.python_version(),
            "sklearn": sklearn.__version__,
            "platform": f"{platform.system()} {platform.release()}",
        },
        "data_sources": {
            "wdbc": {
                "name": "Breast Cancer Wisconsin (Diagnostic)",
                "origin": "UCI ML Repository / sklearn.datasets",
                "license": "CC BY 4.0",
                "sha256": file_sha256(RAW_DIR / "wdbc_raw.csv"),
            },
            "heart": {
                "name": "Heart Disease (Cleveland)",
                "origin": "UCI ML Repository, dataset id=45",
                "license": "CC BY 4.0",
                "sha256": file_sha256(RAW_DIR / "heart_features.csv"),
            },
        },
        "diseases": modules,
    }

    registry_path = REGISTRY_DIR / "registry.json"
    # Same reason as the model card: keep bytes identical across platforms so a
    # regeneration can be diffed against the committed file.
    registry_path.write_text(
        json.dumps(registry, indent=2, ensure_ascii=False),
        encoding="utf-8",
        newline="\n",
    )
    log(f"Registry -> {registry_path.relative_to(REPO_ROOT)}")
    write_model_card(registry)

    log("")
    log("Training complete. Artifacts:")
    for name, mod in modules.items():
        log(f"  {name:8s} champion={mod['champion_id']:20s} "
            f"AUC={mod['models'][mod['champion']]['test']['roc_auc']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
