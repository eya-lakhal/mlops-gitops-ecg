"""Exporte le modèle « champion » du Model Registry MLflow vers un dossier autonome.

Le dossier produit (poids + metadata.json) est ce que l'image Docker embarque : l'API
n'a ainsi besoin ni de MLflow ni d'accès au serveur de suivi pour démarrer.

Les poids sont sauvegardés en `state_dict` (tenseurs uniquement) et relus avec
`torch.load(weights_only=True)` : contrairement à un pickle complet, aucun code
arbitraire ne peut s'exécuter au chargement.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import mlflow
import mlflow.pytorch
import torch
import yaml
from mlflow.tracking import MlflowClient

from ecg.constants import CLASSES, N_FEATURES


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def export(model_name: str, alias: str, out_dir: Path) -> dict:
    client = MlflowClient()
    version = client.get_model_version_by_alias(model_name, alias)
    run = client.get_run(version.run_id)
    params, metrics = run.data.params, run.data.metrics

    model = mlflow.pytorch.load_model(f"models:/{model_name}@{alias}")
    out_dir.mkdir(parents=True, exist_ok=True)
    weights = out_dir / "model.pt"
    torch.save(model.state_dict(), weights)

    metadata = {
        "model_name": model_name,
        "version": str(version.version),
        "alias": alias,
        "run_id": version.run_id,
        "git_commit": run.data.tags.get("git_commit", "unknown"),
        "exported_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "classes": CLASSES,
        "n_features": N_FEATURES,
        "architecture": {
            "conv_channels": [int(c) for c in params["model.conv_channels"].split(",")],
            "lstm_hidden": int(params["model.lstm_hidden"]),
            "dropout": float(params["model.dropout"]),
        },
        "metrics": {k: round(v, 4) for k, v in sorted(metrics.items()) if k.startswith("test_")},
        "sha256": sha256(weights),
    }
    (out_dir / "metadata.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
                                           encoding="utf-8")
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description="Exporte le modèle champion pour l'API")
    parser.add_argument("--params", default="params.yaml")
    parser.add_argument("--alias", default="champion")
    parser.add_argument("--out", default="models/ecg-cnn-bilstm")
    args = parser.parse_args()
    ml = yaml.safe_load(Path(args.params).read_text(encoding="utf-8"))["mlflow"]
    mlflow.set_tracking_uri(os.environ.get("MLFLOW_TRACKING_URI", ml["tracking_uri"]))

    meta = export(ml["registered_model"], args.alias, Path(args.out))
    print(f"Exporté : {meta['model_name']} v{meta['version']} (@{meta['alias']}) -> {args.out}")
    print(f"macro-F1 test = {meta['metrics'].get('test_macro_f1')}  sha256 = {meta['sha256'][:12]}…")


if __name__ == "__main__":
    main()
