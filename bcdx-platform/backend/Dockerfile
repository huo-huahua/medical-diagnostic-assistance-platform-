# --------------------------------------------------------------------------- #
# BC-Dx Platform — backend image
#
# Build context is the repository root, not this directory: the app resolves its
# own paths from `REPO_ROOT`, which is three parents above `app/core/config.py`.
# So the image has to reproduce the repo layout, not just copy `backend/`.
#
#   /app/backend      <- the FastAPI app (working directory at runtime)
#   /app/ml           <- training pipeline + registry
#   /app/knowledge    <- the medical corpus (190 chunks)
# --------------------------------------------------------------------------- #

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Compilers for the few dependencies that still ship as source wheels.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

# torch, CPU only — deliberately installed *before* the requirements file.
#
# `sentence-transformers` pulls torch, and the default wheel on PyPI bundles
# CUDA and is several gigabytes. Installing from PyTorch's CPU index first means
# the later `pip install -r requirements.txt` finds torch already satisfied and
# does not replace it.
#
# If your network cannot reach download.pytorch.org, delete this line — the
# build still works, the image is just much larger.
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install -r ./backend/requirements.txt

COPY backend ./backend
COPY ml ./ml
COPY knowledge ./knowledge
COPY docs ./docs

# Model artifacts are gitignored, so a fresh clone has none. Training runs
# offline from the committed CSVs and is fully seeded, which is exactly what CI
# does — building them here keeps the image self-contained and reproducible.
# The six .joblib files total ~2.4 MB, so this costs seconds, not minutes.
RUN python ml/pipelines/train.py

WORKDIR /app/backend

EXPOSE 8000

# urllib rather than curl: the slim image has no curl, and adding one just for
# a healthcheck is not worth a layer.
HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=3 \
    CMD python -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=8).status == 200 else 1)"

# 0.0.0.0 because the container's network is not the host's loopback.
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
