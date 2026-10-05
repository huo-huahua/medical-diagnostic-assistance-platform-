"""Prediction and explainability routes."""

from __future__ import annotations

import numpy as np
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_user, rate_limit
from app.core.errors import ValidationError
from app.db.models import User
from app.db.session import get_db
from app.ml.registry import get_registry
from app.schemas import (
    BatchPredictRequest,
    BatchPredictResponse,
    Envelope,
    PredictRequest,
    PredictResponse,
)
from app.services.prediction import run_prediction

router = APIRouter(tags=["predict"])


def _envelope(data, request: Request) -> Envelope:
    return Envelope(data=data, request_id=getattr(request.state, "request_id", "-"))


@router.post("/predict", response_model=Envelope,
             dependencies=[Depends(rate_limit(settings.rate_limit_predict, "predict"))])
def predict(payload: PredictRequest, request: Request,
            user: User = Depends(get_current_user),
            db: Session = Depends(get_db)) -> Envelope:
    result = run_prediction(
        db=db,
        user=user,
        disease=payload.disease,
        algo=payload.model,
        features=list(payload.features),
        case_label=payload.case_label,
        persist=payload.persist,
        with_explanation=payload.with_explanation,
        with_narrative=payload.with_narrative,
    )
    return _envelope(PredictResponse(**{
        k: v for k, v in result.items()
        if k in PredictResponse.model_fields
    }), request)


@router.get("/predict/samples", response_model=Envelope)
def sample_specimens(request: Request,
                     disease: str = "breast",
                     n: int = 12,
                     seed: int = 20261004,
                     balanced: bool = True,
                     user: User = Depends(get_current_user)) -> Envelope:
    """Real rows from the public dataset, for the batch page's demo batch.

    Real rather than synthesised on purpose — see `app/services/datasets.py`
    for the sampling bug that motivated it.
    """
    from app.services.datasets import sample_rows

    registry = get_registry()
    mod = registry.disease_info(disease)
    result = sample_rows(
        disease, mod["feature_keys"], n=n, seed=seed, balanced=balanced
    )
    return _envelope({
        "disease": disease,
        "source": result.source,
        "note": result.note,
        "feature_keys": mod["feature_keys"],
        "positive_label_zh": mod["positive_label_zh"],
        "negative_label_zh": mod["negative_label_zh"],
        "rows": result.rows,
    }, request)


@router.post("/predict/batch", response_model=Envelope,
             dependencies=[Depends(rate_limit(settings.rate_limit_predict, "predict"))])
def predict_batch(payload: BatchPredictRequest, request: Request,
                  user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)) -> Envelope:
    """Score many specimens at once.

    Explanations are skipped here: SHAP per row on a 500-row batch would be
    needlessly expensive, and batch scoring is about triage, not attribution.
    """
    registry = get_registry()
    mod = registry.disease_info(payload.disease)
    keys = mod["feature_keys"]
    loaded = registry.get(payload.disease, payload.model)

    results = []
    positive_probs: list[float] = []

    for row_index, row in enumerate(payload.rows):
        missing = [k for k in keys if k not in row]
        if missing:
            raise ValidationError(
                f"Row {row_index} is missing features: {', '.join(missing[:5])}"
                + (" ..." if len(missing) > 5 else "")
            )
        vector = [float(row[k]) for k in keys]
        if not np.all(np.isfinite(vector)):
            raise ValidationError(f"Row {row_index} contains a non-finite value")

        result = run_prediction(
            db=None, user=None,
            disease=payload.disease, algo=payload.model,
            features=vector,
            persist=False, with_explanation=False, with_narrative=False,
        )
        positive_probs.append(result["positive_prob"])
        results.append({
            "row": row_index,
            "verdict": result["verdict"],
            "verdict_label": result["verdict_label"],
            "positive_prob": result["positive_prob"],
            "confidence_band": result["confidence_band"],
        })

    probs = np.asarray(positive_probs, dtype=float)
    # Tally from each row's verdict rather than from a fixed 0.5 cut-off: the
    # champion thresholds are not 0.5 (breast uses a screening-oriented 0.1701),
    # so counting at 0.5 would contradict the per-row labels shown right next
    # to the totals.
    positives = sum(1 for r in results if r["verdict"] == "positive")
    response = BatchPredictResponse(
        disease=payload.disease,
        model_id=loaded.info["id"],
        threshold=loaded.threshold,
        count=len(results),
        positives=positives,
        negatives=len(results) - positives,
        mean_positive_prob=round(float(probs.mean()), 6) if len(probs) else 0.0,
        results=results,
    )
    return _envelope(response, request)
