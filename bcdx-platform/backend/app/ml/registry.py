"""Model registry: loads and caches trained artifacts, exposes prediction."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from app.core.config import REPO_ROOT, settings
from app.core.errors import InferenceError, ModelNotFoundError, AppError, ErrorCode
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class LoadedModel:
    info: dict[str, Any]
    pipeline: Any
    feature_keys: list[str]
    threshold: float


class ModelRegistry:
    """Reads ml/registry/registry.json and lazily loads joblib artifacts."""

    def __init__(self, registry_path: Path | None = None) -> None:
        self.registry_path = registry_path or settings.registry_path
        self._raw: dict[str, Any] = {}
        self._cache: dict[str, LoadedModel] = {}
        self.load_registry()

    # ------------------------------------------------------------------ #
    def load_registry(self) -> None:
        if not self.registry_path.exists():
            raise FileNotFoundError(
                f"Model registry not found at {self.registry_path}. "
                "Run `python ml/pipelines/train.py --disease all` first."
            )
        self._raw = json.loads(self.registry_path.read_text(encoding="utf-8"))
        self._cache.clear()
        diseases = list(self._raw.get("diseases", {}).keys())
        logger.info(f"Registry loaded: diseases={diseases}, "
                    f"generated_at={self._raw.get('generated_at')}")

    # ------------------------------------------------------------------ #
    def diseases(self) -> list[str]:
        return list(self._raw.get("diseases", {}).keys())

    def disease_info(self, disease: str) -> dict[str, Any]:
        mod = self._raw.get("diseases", {}).get(disease)
        if mod is None:
            err = AppError(f"Unknown disease module: {disease}")
            err.code = ErrorCode.INVALID_DISEASE
            err.http_status = 400
            raise err
        return mod

    def resolve_algo(self, disease: str, algo: str | None) -> str:
        mod = self.disease_info(disease)
        models: dict[str, Any] = mod["models"]
        if algo is None or algo == "":
            return mod["champion"]
        if algo not in models:
            raise ModelNotFoundError(
                f"Model '{algo}' is not available for {disease}. "
                f"Available: {', '.join(models)}"
            )
        return algo

    # ------------------------------------------------------------------ #
    def get(self, disease: str, algo: str | None = None) -> LoadedModel:
        algo = self.resolve_algo(disease, algo)
        cache_key = f"{disease}:{algo}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        mod = self.disease_info(disease)
        info = mod["models"][algo]
        path = REPO_ROOT / info["path"]
        if not path.exists():
            raise ModelNotFoundError(f"Artifact missing on disk: {info['path']}")

        try:
            pipeline = joblib.load(path)
        except Exception as exc:
            logger.exception("artifact_load_failed", extra={"path": str(path)})
            raise InferenceError(f"Failed to load model artifact: {exc}") from exc

        loaded = LoadedModel(
            info=info,
            pipeline=pipeline,
            feature_keys=list(mod["feature_keys"]),
            threshold=float(info["threshold"]),
        )
        self._cache[cache_key] = loaded
        logger.info(f"Model loaded into memory: {info['id']} "
                    f"({path.stat().st_size / 1024:.0f} KB)")
        return loaded

    def warm_up(self) -> None:
        """Preload every artifact so the first request is not slow."""
        for disease in self.diseases():
            mod = self.disease_info(disease)
            for algo in mod["models"]:
                try:
                    self.get(disease, algo)
                except Exception as exc:  # pragma: no cover - defensive
                    logger.warning(f"Warm-up skipped {disease}/{algo}: {exc}")

    # ------------------------------------------------------------------ #
    def predict(
        self,
        disease: str,
        algo: str | None,
        features: list[float],
    ) -> tuple[LoadedModel, np.ndarray, float]:
        """Return (model, feature_vector, positive_probability)."""
        model = self.get(disease, algo)
        if len(features) != len(model.feature_keys):
            raise InferenceError(
                f"Expected {len(model.feature_keys)} features, received {len(features)}"
            )
        try:
            frame = pd.DataFrame([features], columns=model.feature_keys)
            proba = model.pipeline.predict_proba(frame)
            return model, np.asarray(features, dtype=float), float(proba[0][1])
        except Exception as exc:
            logger.exception("inference_failed",
                             extra={"disease": disease, "algo": algo})
            raise InferenceError(f"Model inference failed: {exc}") from exc


@lru_cache(maxsize=1)
def get_registry() -> ModelRegistry:
    return ModelRegistry()


def confidence_band(prob: float, threshold: float) -> str:
    """Map a calibrated probability to a human-facing confidence band."""
    margin = abs(prob - threshold)
    if margin >= 0.40:
        return "very_high"
    if margin >= 0.20:
        return "high"
    if margin >= 0.08:
        return "moderate"
    return "low"
