"""Tests de l'API avec un modèle aux poids aléatoires : ils vérifient le contrat
(schémas, codes HTTP, métriques), pas la qualité des prédictions."""

import hashlib
import json

import pytest
import torch
from fastapi.testclient import TestClient

from ecg.api import MAX_BEATS, app
from ecg.constants import CLASSES, N_FEATURES
from ecg.model import CnnBiLstm


def write_model(model_dir, tamper=False):
    model_dir.mkdir(parents=True, exist_ok=True)
    torch.manual_seed(0)
    weights = model_dir / "model.pt"
    torch.save(CnnBiLstm().state_dict(), weights)
    meta = {
        "model_name": "ecg-cnn-bilstm", "version": "42", "alias": "champion", "run_id": "test",
        "classes": CLASSES, "n_features": N_FEATURES,
        "architecture": {"conv_channels": [32, 64], "lstm_hidden": 64, "dropout": 0.3},
        "metrics": {}, "sha256": hashlib.sha256(weights.read_bytes()).hexdigest(),
    }
    (model_dir / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    if tamper:
        weights.write_bytes(weights.read_bytes() + b"\x00")


@pytest.fixture
def client(tmp_path, monkeypatch):
    write_model(tmp_path / "model")
    monkeypatch.setenv("MODEL_DIR", str(tmp_path / "model"))
    with TestClient(app) as c:  # le « with » déclenche le lifespan (chargement du modèle)
        yield c


def beats(n):
    return [[0.1] * N_FEATURES for _ in range(n)]


def test_health_and_ready(client):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/ready").json()["model_version"] == "42"


def test_predict_returns_one_prediction_per_beat(client):
    response = client.post("/predict", json={"beats": beats(3)})
    assert response.status_code == 200
    body = response.json()
    assert body["model_version"] == "42"
    assert len(body["predictions"]) == 3
    pred = body["predictions"][0]
    assert pred["predicted_class"] in CLASSES
    assert pred["is_anomaly"] == (pred["predicted_class"] != "N")
    assert sum(pred["probabilities"].values()) == pytest.approx(1.0, abs=1e-3)


@pytest.mark.parametrize("payload", [
    {"beats": []},                                  # lot vide
    {"beats": beats(MAX_BEATS + 1)},                # lot trop grand
    {"beats": [[0.1] * (N_FEATURES - 1)]},          # mauvaise longueur
    {"beats": [["abc"] * N_FEATURES]},              # pas des nombres
    {"wrong": []},                                  # champ manquant
])
def test_predict_rejects_invalid_payloads(client, payload):
    assert client.post("/predict", json=payload).status_code == 422


def test_metrics_expose_red_and_business_signals(client):
    client.post("/predict", json={"beats": beats(2)})
    text = client.get("/metrics").text
    assert 'http_requests_total{method="POST",route="/predict",status="200"}' in text
    assert "http_request_duration_seconds_bucket" in text
    assert 'ecg_predictions_total{model_version="42"' in text
    assert 'ecg_model_info{model_name="ecg-cnn-bilstm",run_id="test",version="42"} 1.0' in text


def test_metrics_route_labels_have_bounded_cardinality(client):
    client.get("/docs")
    client.get("/scan/random-1")
    client.get("/scan/random-2")
    text = client.get("/metrics").text
    assert 'route="/docs",status="200"' in text
    assert 'route="unmatched",status="404"' in text
    assert "random-1" not in text


def test_tampered_weights_prevent_startup(tmp_path, monkeypatch):
    write_model(tmp_path / "model", tamper=True)
    monkeypatch.setenv("MODEL_DIR", str(tmp_path / "model"))
    with pytest.raises(RuntimeError, match="SHA-256"), TestClient(app):
        pass
