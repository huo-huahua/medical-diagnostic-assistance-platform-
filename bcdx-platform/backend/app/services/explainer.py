"""SHAP-based explainability service.

Returns *structured numeric contributions* rather than a pre-rendered PNG,
so the frontend can draw an interactive chart.

Artifact layout note
--------------------
Training wraps each model as::

    CalibratedClassifierCV( Pipeline(StandardScaler -> Classifier) )

so the object loaded from disk is a calibrator, not a Pipeline. Every accessor
below therefore unwraps layer by layer, tolerating both the calibrated and the
raw Pipeline layout. Getting this wrong is how the first version crashed with
``'CalibratedClassifierCV' object has no attribute 'named_steps'``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.core.logging import get_logger
from app.ml.registry import LoadedModel

logger = get_logger(__name__)

_explainer_cache: dict[str, object] = {}


# --------------------------------------------------------------------------- #
# Unwrapping helpers
# --------------------------------------------------------------------------- #

def unwrap_estimator(artifact) -> object:
    """Drill through CalibratedClassifierCV -> Pipeline -> final estimator."""
    node = artifact

    # CalibratedClassifierCV stores fitted clones in calibrated_classifiers_.
    if hasattr(node, "calibrated_classifiers_"):
        try:
            inner = node.calibrated_classifiers_[0]
            candidate = getattr(inner, "estimator", None)
            if candidate is None:
                candidate = getattr(inner, "base_estimator", None)
            if candidate is not None:
                node = candidate
        except (IndexError, AttributeError) as exc:
            logger.debug(f"calibrator unwrap failed: {exc}")

    # Pipeline -> final step
    if hasattr(node, "named_steps"):
        steps = list(node.named_steps.values())
        if steps:
            node = steps[-1]

    return node


def get_scaler(artifact):
    """Return the StandardScaler inside the pipeline, or None."""
    node = artifact
    if hasattr(node, "calibrated_classifiers_"):
        try:
            inner = node.calibrated_classifiers_[0]
            node = getattr(inner, "estimator", None) or getattr(
                inner, "base_estimator", None
            ) or node
        except (IndexError, AttributeError):
            pass
    if hasattr(node, "named_steps"):
        return node.named_steps.get("scaler")
    return None


def _to_scaled(model: LoadedModel, raw: np.ndarray) -> np.ndarray:
    scaler = get_scaler(model.pipeline)
    if scaler is None:
        return np.asarray(raw, dtype=float).reshape(1, -1)
    frame = pd.DataFrame([raw], columns=model.feature_keys)
    return scaler.transform(frame)


# --------------------------------------------------------------------------- #
# Explainer construction
# --------------------------------------------------------------------------- #

def _build_explainer(model: LoadedModel, algo: str, background_scaled: np.ndarray):
    import shap

    inner = unwrap_estimator(model.pipeline)

    if algo == "lr":
        masker = shap.maskers.Independent(
            background_scaled, max_samples=min(100, len(background_scaled))
        )
        return shap.LinearExplainer(inner, masker)

    return shap.TreeExplainer(inner)


def _normalise_values(values) -> np.ndarray:
    """Collapse SHAP's many return shapes into a (n_features,) vector."""
    if isinstance(values, list):
        # [neg_class_array, pos_class_array]
        arr = np.asarray(values[1] if len(values) > 1 else values[0])
    else:
        arr = np.asarray(values)

    if arr.ndim == 3:          # (n_samples, n_features, n_classes)
        arr = arr[:, :, 1]
    if arr.ndim == 2:          # (n_samples, n_features)
        arr = arr[0]
    if arr.ndim == 0:
        arr = arr.reshape(1)

    return np.nan_to_num(arr.astype(float), nan=0.0, posinf=0.0, neginf=0.0)


def _extract_base(explainer) -> float:
    base = getattr(explainer, "expected_value", 0.0)
    if isinstance(base, (list, tuple, np.ndarray)):
        flat = np.asarray(base).ravel()
        if flat.size == 0:
            return 0.0
        return float(flat[1] if flat.size > 1 else flat[0])
    try:
        return float(base)
    except (TypeError, ValueError):
        return 0.0


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def compute_contributions(
    model: LoadedModel,
    algo: str,
    raw_features: np.ndarray,
    background: np.ndarray,
) -> tuple[np.ndarray, float]:
    """Return (contribution vector, base value) for a single sample.

    Positive contributions push toward the positive class
    (malignant for breast, disease-present for heart).
    """
    scaled = _to_scaled(model, raw_features)

    try:
        cache_key = f"{model.info['id']}:{scaled.shape[1]}"
        if cache_key not in _explainer_cache:
            background_scaled = np.vstack(
                [_to_scaled(model, row) for row in background[:200]]
            )
            _explainer_cache[cache_key] = _build_explainer(
                model, algo, background_scaled
            )
            logger.debug(f"SHAP explainer built and cached: {cache_key}")

        explainer = _explainer_cache[cache_key]
        values = explainer.shap_values(scaled)
        contrib = _normalise_values(values)

        # Dimension guard: fall back if SHAP returned something unexpected.
        if contrib.shape[0] != len(model.feature_keys):
            raise ValueError(
                f"SHAP returned {contrib.shape[0]} values for "
                f"{len(model.feature_keys)} features"
            )

        return contrib, _extract_base(explainer)

    except Exception as exc:
        logger.warning(
            f"SHAP unavailable for {model.info['id']} ({exc}); "
            "using deterministic importance fallback"
        )
        return _fallback_contributions(model, scaled), 0.0


def _fallback_contributions(model: LoadedModel, scaled: np.ndarray) -> np.ndarray:
    """Deterministic fallback: coef x value for linear, gain for trees."""
    inner = unwrap_estimator(model.pipeline)
    row = np.asarray(scaled).reshape(1, -1)

    if hasattr(inner, "coef_"):
        coef = np.asarray(inner.coef_).ravel()
        if coef.shape[0] == row.shape[1]:
            return coef * row[0]
    if hasattr(inner, "feature_importances_"):
        return np.asarray(inner.feature_importances_).ravel()
    return np.zeros(len(model.feature_keys))
