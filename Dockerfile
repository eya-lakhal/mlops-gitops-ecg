# syntax=docker/dockerfile:1
# Image de l'API de prédiction ECG : multi-stage, torch CPU, utilisateur non-root.

ARG PYTHON_VERSION=3.11

# ---- Étape 1 : construction de l'environnement Python ------------------------------------
FROM python:${PYTHON_VERSION}-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH

# torch CPU en premier, dans sa propre couche : la plus lourde (~700 Mo), réutilisée depuis
# le cache tant que la version ne change pas. L'index CPU évite les Go de librairies CUDA.
ARG TORCH_VERSION=2.15.0
RUN pip install "torch==${TORCH_VERSION}" --index-url https://download.pytorch.org/whl/cpu

# Le code change souvent : copié après les dépendances lourdes pour préserver le cache.
WORKDIR /build
COPY pyproject.toml ./
COPY src ./src
RUN pip install ".[api]"

# ---- Étape 2 : image finale minimale -----------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS runtime

LABEL org.opencontainers.image.title="ecg-api" \
      org.opencontainers.image.description="API de détection d'anomalies ECG (CNN-BiLSTM, MIT-BIH)" \
      org.opencontainers.image.source="https://github.com/eya-lakhal/mlops-gitops-ecg"

ENV PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MODEL_DIR=/app/models/ecg-cnn-bilstm \
    TORCH_NUM_THREADS=1

# Utilisateur dédié sans shell ni home, avec un UID numérique fixe : Kubernetes peut ainsi
# vérifier « runAsNonRoot » sans lire /etc/passwd.
RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
# Modèle en lecture seule pour l'utilisateur app (propriétaire root).
COPY models/ ./models/

USER 10001:10001
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import urllib.request, sys; sys.exit(urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).status != 200)"]

CMD ["uvicorn", "ecg.api:app", "--host", "0.0.0.0", "--port", "8000"]
