"""Entraînement du CNN-BiLSTM avec suivi MLflow.

Chaque exécution crée un « run » MLflow contenant : paramètres, courbes par époque,
métriques de test (DS2), matrice de confusion, modèle avec signature, et une nouvelle
version dans le Model Registry. L'alias « champion » est déplacé seulement si la
nouvelle version bat l'actuelle sur le macro-F1 de test.
"""

from __future__ import annotations

import argparse
import copy
import os
import random
import subprocess
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # pas d'affichage graphique : on génère des fichiers

import mlflow
import mlflow.pytorch
import numpy as np
import torch
import yaml
from mlflow.exceptions import MlflowException
from mlflow.models import infer_signature
from mlflow.tracking import MlflowClient
from sklearn.metrics import ConfusionMatrixDisplay, classification_report, f1_score
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

from ecg.constants import CLASSES
from ecg.data import describe, load_or_prepare
from ecg.model import CnnBiLstm

LABELS = list(range(len(CLASSES)))


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def class_weights(y: np.ndarray, n_classes: int, power: float) -> torch.Tensor:
    """Poids inverses à la fréquence, adoucis par `power` (0 = aucun, 1 = équilibrage complet)."""
    counts = np.maximum(np.bincount(y, minlength=n_classes), 1).astype(np.float64)
    weights = (counts.sum() / (n_classes * counts)) ** power
    return torch.tensor(weights / weights.mean(), dtype=torch.float32)


@torch.no_grad()
def predict(model: nn.Module, x: np.ndarray, batch_size: int = 2048) -> np.ndarray:
    model.eval()
    preds = [model(torch.from_numpy(x[i:i + batch_size])).argmax(dim=1).numpy()
             for i in range(0, len(x), batch_size)]
    return np.concatenate(preds)


def flatten(cfg: dict, prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in cfg.items():
        name = f"{prefix}{key}"
        if isinstance(value, dict):
            out.update(flatten(value, f"{name}."))
        else:
            out[name] = ",".join(map(str, value)) if isinstance(value, list) else str(value)
    return out


def git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def promote_if_better(client: MlflowClient, name: str, version: str, score: float) -> bool:
    """Place l'alias « champion » sur `version` si son macro-F1 de test dépasse celui en place."""
    try:
        champion = client.get_model_version_by_alias(name, "champion")
        best = client.get_run(champion.run_id).data.metrics.get("test_macro_f1", -1.0)
    except MlflowException:
        best = -1.0
    if score > best:
        client.set_registered_model_alias(name, "champion", version)
        return True
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Entraîne le CNN-BiLSTM et le suit dans MLflow")
    parser.add_argument("--params", default="params.yaml")
    args = parser.parse_args()
    params = yaml.safe_load(Path(args.params).read_text(encoding="utf-8"))
    d, t, m, ml = params["data"], params["train"], params["model"], params["mlflow"]
    set_seed(t["seed"])

    raw_dir, processed_dir = Path(d["raw_dir"]), Path(d["processed_dir"])
    x1, y1, rec1 = load_or_prepare("DS1", raw_dir, processed_dir)
    x_test, y_test, _ = load_or_prepare("DS2", raw_dir, processed_dir)

    # Validation par patient : des enregistrements entiers de DS1 sont mis de côté
    val_mask = np.isin(rec1, d["val_records"])
    x_train, y_train = x1[~val_mask], y1[~val_mask]
    x_val, y_val = x1[val_mask], y1[val_mask]
    for name, y in (("train", y_train), ("val", y_val), ("test (DS2)", y_test)):
        print(describe(name, y))

    mlflow.set_tracking_uri(os.environ.get("MLFLOW_TRACKING_URI", ml["tracking_uri"]))
    mlflow.set_experiment(ml["experiment"])

    with mlflow.start_run() as run:
        mlflow.set_tags({"git_commit": git_commit(),
                         "split": "inter-patient de Chazal (DS1 train/val, DS2 test)"})
        mlflow.log_params(flatten(params))
        mlflow.log_params({"n_train": len(y_train), "n_val": len(y_val), "n_test": len(y_test)})

        model = CnnBiLstm(n_classes=len(CLASSES), conv_channels=tuple(m["conv_channels"]),
                          lstm_hidden=m["lstm_hidden"], dropout=m["dropout"])
        weights = class_weights(y_train, len(CLASSES), t["class_weight_power"])
        mlflow.log_params({f"class_weight.{c}": round(float(w), 3)
                           for c, w in zip(CLASSES, weights)})
        loss_fn = nn.CrossEntropyLoss(weight=weights)
        optimizer = torch.optim.AdamW(model.parameters(), lr=t["lr"],
                                      weight_decay=t["weight_decay"])
        loader = DataLoader(TensorDataset(torch.from_numpy(x_train), torch.from_numpy(y_train)),
                            batch_size=t["batch_size"], shuffle=True)

        best_f1, best_state, bad_epochs = -1.0, None, 0
        for epoch in range(t["epochs"]):
            model.train()
            total = 0.0
            for xb, yb in loader:
                optimizer.zero_grad()
                loss = loss_fn(model(xb), yb)
                loss.backward()
                optimizer.step()
                total += loss.item() * len(yb)
            train_loss = total / len(y_train)
            val_f1 = f1_score(y_val, predict(model, x_val), labels=LABELS, average="macro",
                              zero_division=0)
            mlflow.log_metrics({"train_loss": train_loss, "val_macro_f1": val_f1}, step=epoch)
            print(f"époque {epoch + 1:02d}  loss={train_loss:.4f}  val_macro_f1={val_f1:.4f}")

            if val_f1 > best_f1:  # early stopping sur le macro-F1 de validation
                best_f1, best_state, bad_epochs = val_f1, copy.deepcopy(model.state_dict()), 0
            else:
                bad_epochs += 1
                if bad_epochs >= t["patience"]:
                    print(f"Arrêt anticipé : pas d'amélioration depuis {bad_epochs} époques")
                    break

        model.load_state_dict(best_state)
        mlflow.log_metric("best_val_macro_f1", best_f1)

        # Évaluation finale sur DS2 : patients jamais vus pendant l'entraînement
        y_pred = predict(model, x_test)
        report = classification_report(y_test, y_pred, labels=LABELS, target_names=CLASSES,
                                       output_dict=True, zero_division=0)
        metrics = {"test_accuracy": report["accuracy"],
                   "test_macro_f1": report["macro avg"]["f1-score"]}
        for c in CLASSES:
            for k in ("precision", "recall", "f1-score"):
                metrics[f"test_{c}_{k.replace('-score', '')}"] = report[c][k]
        mlflow.log_metrics(metrics)
        mlflow.log_text(classification_report(y_test, y_pred, labels=LABELS,
                                              target_names=CLASSES, digits=4, zero_division=0),
                        "classification_report.txt")
        disp = ConfusionMatrixDisplay.from_predictions(y_test, y_pred, labels=LABELS,
                                                       display_labels=CLASSES, normalize="true",
                                                       values_format=".2f", cmap="Blues")
        disp.ax_.set_title("Matrice de confusion DS2 (normalisée par ligne)")
        mlflow.log_figure(disp.figure_, "confusion_matrix.png")

        # Modèle + signature (contrat d'entrée/sortie) + enregistrement dans le Registry
        model.eval()
        example = x_test[:5]
        with torch.no_grad():
            signature = infer_signature(example, model(torch.from_numpy(example)).numpy())
        mlflow.pytorch.log_model(model, name="model", signature=signature,
                                 input_example=example[:2],
                                 registered_model_name=ml["registered_model"])

        client = MlflowClient()
        version = client.search_model_versions(
            f"name='{ml['registered_model']}' and run_id='{run.info.run_id}'")[0].version
        promoted = promote_if_better(client, ml["registered_model"], version,
                                     metrics["test_macro_f1"])

    print(f"\nTest DS2 : accuracy={metrics['test_accuracy']:.4f}  "
          f"macro_f1={metrics['test_macro_f1']:.4f}")
    print(f"Version {version} de '{ml['registered_model']}' enregistrée"
          f"{' et promue « champion »' if promoted else ' (champion inchangé)'}")


if __name__ == "__main__":
    main()
