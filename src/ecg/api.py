"""API de prédiction ECG (FastAPI) instrumentée pour Prometheus.

Routes :
- POST /predict : classe un lot de battements (260 valeurs chacun)
- GET  /health  : liveness (le processus répond)
- GET  /ready   : readiness (le modèle est chargé, on peut recevoir du trafic)
- GET  /model   : version et métriques du modèle servi
- GET  /metrics : métriques au format Prometheus
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

import torch
from fastapi import FastAPI, HTTPException, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from pydantic import BaseModel, Field

from ecg.constants import CLASS_DESCRIPTIONS, N_FEATURES
from ecg.model import CnnBiLstm

MAX_BEATS = 256
logger = logging.getLogger("ecg.api")

# --- Métriques Prometheus ------------------------------------------------------------------
# Signaux « RED » (Rate, Errors, Duration) : base des SLO de la Phase 5.
REQUESTS = Counter("http_requests_total", "Requêtes HTTP traitées",
                   ["method", "route", "status"])
LATENCY = Histogram("http_request_duration_seconds", "Durée des requêtes HTTP",
                    ["method", "route"],
                    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0))
# Signaux métier : distribution des prédictions et de la confiance (base du suivi de dérive).
PREDICTIONS = Counter("ecg_predictions_total", "Battements classés",
                      ["predicted_class", "model_version"])
CONFIDENCE = Histogram("ecg_prediction_confidence", "Probabilité de la classe prédite",
                       buckets=(0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.99, 1.0))
BATCH_SIZE = Histogram("ecg_batch_size", "Nombre de battements par requête",
                       buckets=(1, 2, 5, 10, 25, 50, 100, MAX_BEATS))
MODEL_INFO = Gauge("ecg_model_info", "Modèle servi (valeur constante 1)",
                   ["model_name", "version", "run_id"])


# --- Chargement du modèle ------------------------------------------------------------------
def load_model(model_dir: Path) -> tuple[CnnBiLstm, dict]:
    """Charge poids + métadonnées et vérifie l'intégrité des poids (SHA-256)."""
    meta = json.loads((model_dir / "metadata.json").read_text(encoding="utf-8"))
    weights = model_dir / "model.pt"
    digest = hashlib.sha256(weights.read_bytes()).hexdigest()
    if digest != meta["sha256"]:
        raise RuntimeError(f"Empreinte SHA-256 invalide pour {weights} : fichier altéré")
    if meta["n_features"] != N_FEATURES:
        raise RuntimeError(f"Le modèle attend {meta['n_features']} valeurs, le code {N_FEATURES}")
    arch = meta["architecture"]
    model = CnnBiLstm(n_classes=len(meta["classes"]), conv_channels=tuple(arch["conv_channels"]),
                      lstm_hidden=arch["lstm_hidden"], dropout=arch["dropout"])
    model.load_state_dict(torch.load(weights, map_location="cpu", weights_only=True))
    model.eval()
    return model, meta


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1 thread par défaut : en conteneur, le parallélisme vient du nombre de réplicas,
    # et trop de threads par rapport à la limite CPU provoque du throttling.
    torch.set_num_threads(int(os.environ.get("TORCH_NUM_THREADS", "1")))
    model_dir = Path(os.environ.get("MODEL_DIR", "models/ecg-cnn-bilstm"))
    app.state.model, app.state.meta = load_model(model_dir)
    meta = app.state.meta
    MODEL_INFO.labels(meta["model_name"], meta["version"], meta["run_id"]).set(1)
    logger.info("Modèle %s v%s chargé depuis %s", meta["model_name"], meta["version"], model_dir)
    yield


app = FastAPI(title="ECG Anomaly Detection API", version="0.1.0", lifespan=lifespan)


@app.middleware("http")
async def prometheus_middleware(request: Request, call_next):
    start = time.perf_counter()
    status = 500  # valeur conservée si le traitement lève une exception non gérée
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        # Le gabarit de route (« /predict ») et non l'URL brute : cardinalité bornée.
        # Les routes internes de FastAPI (/docs, /openapi.json) n'ont pas de gabarit : on
        # garde leur chemin ; les 404 sont regroupées pour qu'un scan d'URL ne crée pas
        # une série temporelle par chemin inventé.
        route = request.scope.get("route")
        path = getattr(route, "path", None) or ("unmatched" if status == 404 else request.url.path)
        if path != "/metrics":
            LATENCY.labels(request.method, path).observe(time.perf_counter() - start)
            REQUESTS.labels(request.method, path, str(status)).inc()


# --- Schémas -------------------------------------------------------------------------------
FiniteFloat = Annotated[float, Field(allow_inf_nan=False)]
Beat = Annotated[list[FiniteFloat], Field(min_length=N_FEATURES, max_length=N_FEATURES)]


class PredictRequest(BaseModel):
    beats: list[Beat] = Field(
        min_length=1, max_length=MAX_BEATS,
        description=f"Battements : {N_FEATURES} valeurs = 256 points normalisés + 4 features RR")


class BeatPrediction(BaseModel):
    predicted_class: str
    description: str
    is_anomaly: bool
    confidence: float
    probabilities: dict[str, float]


class PredictResponse(BaseModel):
    model_version: str
    predictions: list[BeatPrediction]


# --- Routes --------------------------------------------------------------------------------
@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/ready")
def ready(request: Request) -> dict:
    if getattr(request.app.state, "model", None) is None:
        raise HTTPException(status_code=503, detail="Modèle non chargé")
    return {"status": "ready", "model_version": request.app.state.meta["version"]}


@app.get("/model")
def model_info(request: Request) -> dict:
    return request.app.state.meta


@app.post("/predict", response_model=PredictResponse)
def predict(body: PredictRequest, request: Request) -> PredictResponse:
    # Route synchrone : FastAPI l'exécute dans un pool de threads, l'inférence
    # (bloquante) ne gèle donc pas la boucle d'événements.
    model, meta = request.app.state.model, request.app.state.meta
    classes, version = meta["classes"], meta["version"]
    with torch.inference_mode():
        probs = torch.softmax(model(torch.tensor(body.beats, dtype=torch.float32)), dim=1)
    BATCH_SIZE.observe(len(body.beats))

    predictions = []
    for row in probs.tolist():
        idx = max(range(len(row)), key=row.__getitem__)
        cls = classes[idx]
        PREDICTIONS.labels(cls, version).inc()
        CONFIDENCE.observe(row[idx])
        predictions.append(BeatPrediction(
            predicted_class=cls,
            description=CLASS_DESCRIPTIONS.get(cls, cls),
            is_anomaly=cls != "N",
            confidence=round(row[idx], 4),
            probabilities={c: round(p, 4) for c, p in zip(classes, row)},
        ))
    return PredictResponse(model_version=version, predictions=predictions)


@app.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
