"""Model registry routes: disease metadata, feature schema, metrics."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.core.deps import bearer_scheme_optional, get_current_user
from app.db.models import User
from app.ml.registry import get_registry
from app.schemas import DiseaseInfoOut, Envelope

router = APIRouter(prefix="/models", tags=["models"])


def _envelope(data, request: Request) -> Envelope:
    return Envelope(data=data, request_id=getattr(request.state, "request_id", "-"))


def _to_out(mod: dict) -> DiseaseInfoOut:
    return DiseaseInfoOut(
        disease=mod["disease"],
        display_zh=mod["display_zh"],
        display_en=mod["display_en"],
        n_samples=mod["n_samples"],
        n_features=mod["n_features"],
        positive_label_zh=mod["positive_label_zh"],
        negative_label_zh=mod["negative_label_zh"],
        class_balance=mod["class_balance"],
        feature_schema=mod["feature_schema"],
        default_values=mod["default_values"],
        models=list(mod["models"].values()),
        champion=mod["champion"],
        champion_id=mod["champion_id"],
    )


@router.get("", response_model=Envelope)
def list_diseases(request: Request) -> Envelope:
    """Public: the landing page needs feature metadata before sign-in."""
    registry = get_registry()
    return _envelope(
        [_to_out(registry.disease_info(d)) for d in registry.diseases()],
        request,
    )


@router.get("/registry", response_model=Envelope)
def raw_registry(request: Request, user: User = Depends(get_current_user)) -> Envelope:
    """Full registry document, including environment and data provenance."""
    registry = get_registry()
    return _envelope(registry._raw, request)


@router.get("/{disease}", response_model=Envelope)
def get_disease(disease: str, request: Request) -> Envelope:
    registry = get_registry()
    return _envelope(_to_out(registry.disease_info(disease)), request)


@router.get("/{disease}/{algo}/metrics", response_model=Envelope)
def get_model_metrics(disease: str, algo: str, request: Request) -> Envelope:
    registry = get_registry()
    resolved = registry.resolve_algo(disease, algo)
    mod = registry.disease_info(disease)
    return _envelope(mod["models"][resolved], request)
