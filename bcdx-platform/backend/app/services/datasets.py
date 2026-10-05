"""Sampling real rows from the public datasets.

Used to populate the batch-evaluation page with a demonstration batch.

Why this module exists instead of generating numbers in the browser
-------------------------------------------------------------------
The first version of the batch demo synthesised feature values by sampling
uniformly inside each feature's `[min, max]` range. That looked reasonable and
was quietly wrong: the *maximum* of a feature is almost always set by the
positive class, whose values run higher, so a uniform draw over the whole range
is centred near the positive population's mean rather than between the classes.
Every synthetic row came back "malignant at ~100%", which is a property of the
sampler, not of the model — a demo that teaches the wrong thing.

Sampling real rows removes the guesswork entirely, and lets the page show the
model's verdict next to the dataset's actual label.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from app.core.config import REPO_ROOT
from app.core.errors import ValidationError
from app.core.logging import get_logger

logger = get_logger(__name__)

RAW_DIR = REPO_ROOT / "ml" / "data" / "raw"

_FILES = {
    "breast": ("wdbc_raw.csv", "Diagnosis"),
    "heart": ("heart_features.csv", None),
}


@dataclass(frozen=True)
class SampleSet:
    disease: str
    rows: list[dict[str, Any]]
    source: str
    note: str


@lru_cache(maxsize=2)
def _load_frame(disease: str) -> tuple[pd.DataFrame, np.ndarray]:
    """Return (features, binary labels) for a disease module.

    Label convention matches the rest of the project: **0 = negative,
    1 = positive**. For the heart data the UCI `num` field is binarised at > 0,
    which is the standard convention for that dataset.
    """
    filename, label_col = _FILES[disease]
    path: Path = RAW_DIR / filename
    if not path.exists():
        raise ValidationError(f"Raw dataset missing: {path}")

    frame = pd.read_csv(path)
    frame = frame.replace("?", np.nan)

    if disease == "breast":
        raw_label = frame.pop(label_col).astype(str).str.strip().str.upper()
        labels = (raw_label == "M").astype(int).to_numpy()
    else:
        targets = pd.read_csv(RAW_DIR / "heart_targets.csv")
        labels = (targets.iloc[:, 0].to_numpy() > 0).astype(int)

    features = frame.apply(lambda c: pd.to_numeric(c, errors="coerce"))
    features = features.fillna(features.median(numeric_only=True))
    return features, labels


def _balanced_index(labels: np.ndarray, n: int, rng: np.random.Generator) -> np.ndarray:
    """Pick ~half from each class so a demo batch shows both outcomes.

    A purely random draw from WDBC would usually be usable too, but it can come
    back lopsided, and a batch where every row shares one verdict illustrates
    nothing.
    """
    pos = np.flatnonzero(labels == 1)
    neg = np.flatnonzero(labels == 0)
    n_pos = min(len(pos), n // 2)
    n_neg = min(len(neg), n - n_pos)
    # Top up from the larger class if one side ran out.
    remaining = n - n_pos - n_neg
    if remaining > 0:
        extra_pool = neg if len(neg) - n_neg >= len(pos) - n_pos else pos
        used = n_neg if extra_pool is neg else n_pos
        extra = min(remaining, len(extra_pool) - used)
        if extra_pool is neg:
            n_neg += extra
        else:
            n_pos += extra

    picked = np.concatenate([
        rng.choice(pos, size=n_pos, replace=False),
        rng.choice(neg, size=n_neg, replace=False),
    ])
    rng.shuffle(picked)
    return picked


def sample_rows(
    disease: str,
    feature_keys: list[str],
    *,
    n: int = 12,
    seed: int = 20261004,
    balanced: bool = True,
    with_labels: bool = True,
) -> SampleSet:
    """Draw `n` real specimens, returned in the model's feature order."""
    if disease not in _FILES:
        raise ValidationError(f"Unsupported disease module: {disease}")
    if not 1 <= n <= 200:
        raise ValidationError("n must be between 1 and 200")

    features, labels = _load_frame(disease)
    missing = [k for k in feature_keys if k not in features.columns]
    if missing:
        raise ValidationError(
            f"Dataset columns do not match the registry for {disease}: "
            f"missing {missing[:5]}"
        )

    rng = np.random.default_rng(seed)
    idx = (
        _balanced_index(labels, n, rng)
        if balanced
        else rng.choice(len(features), size=min(n, len(features)), replace=False)
    )

    rows: list[dict[str, Any]] = []
    for order, i in enumerate(idx, start=1):
        values = {
            key: float(features.iloc[i][key])
            for key in feature_keys
        }
        row: dict[str, Any] = {
            "case_label": f"{'WDBC' if disease == 'breast' else 'UCI'}-{int(i) + 1:03d}",
            "features": values,
        }
        if with_labels:
            row["true_label"] = int(labels[i])
        rows.append(row)

    filename, _ = _FILES[disease]
    return SampleSet(
        disease=disease,
        rows=rows,
        source=filename,
        note=(
            f"以下 {len(rows)} 行取自公开数据集的真实样本"
            + ("（每类各取一半，便于同时看到两种判定）" if balanced else "（随机抽样）")
            + "，附带数据集给出的真实标签供对照，不是模拟数据。"
        ),
    )
