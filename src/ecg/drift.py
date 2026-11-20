"""Surveillance de la dérive des données avec Evidently.

Compare une population de RÉFÉRENCE (battements d'entraînement, DS1) à une population
COURANTE et répond à la question : « les données que voit le modèle ressemblent-elles
encore à celles sur lesquelles il a appris ? ». Le modèle n'a pas besoin des vraies
étiquettes pour cela : c'est un signal d'alerte précoce, disponible immédiatement en
production, alors que les étiquettes (diagnostic d'un cardiologue) arrivent tard ou jamais.

Les 260 valeurs brutes sont résumées en descripteurs interprétables (rythme, forme du
battement) et complétées par les sorties du modèle (dérive des prédictions).

Scénarios :
- ds2           : nouveaux patients (DS2), écart « naturel » d'une population à l'autre ;
- capteur_bruite : DS2 + bruit de mesure et dérive de ligne de base (électrode décollée) ;
- tachycardie   : DS2 avec un rythme accéléré de 35 % (population plus jeune ou à l'effort).
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import mlflow
import numpy as np
import pandas as pd
import torch
import yaml
from evidently import DataDefinition, Dataset, Report
from evidently.presets import DataDriftPreset

from ecg.api import load_model
from ecg.constants import BEFORE, CLASSES, N_SAMPLES
from ecg.data import load_or_prepare

FEATURES = ["rr_pre", "rr_post", "rr_pre_ratio", "rr_post_ratio", "r_amplitude",
            "amplitude_crete_a_crete", "energie_hf", "asymetrie", "confiance", "classe_predite"]


def describe_beats(x: np.ndarray, model: torch.nn.Module) -> pd.DataFrame:
    """Résume chaque battement en descripteurs interprétables + sortie du modèle."""
    sig, rr = x[:, :N_SAMPLES], x[:, N_SAMPLES:]
    centered = sig - sig.mean(axis=1, keepdims=True)
    std = sig.std(axis=1) + 1e-6
    with torch.inference_mode():
        probs = torch.softmax(model(torch.from_numpy(x)), dim=1).numpy()
    return pd.DataFrame({
        "rr_pre": rr[:, 0],
        "rr_post": rr[:, 1],
        "rr_pre_ratio": rr[:, 2],
        "rr_post_ratio": rr[:, 3],
        "r_amplitude": sig[:, BEFORE],
        "amplitude_crete_a_crete": sig.max(axis=1) - sig.min(axis=1),
        # énergie des variations rapides : augmente avec le bruit de mesure
        "energie_hf": np.mean(np.diff(sig, axis=1) ** 2, axis=1),
        "asymetrie": np.mean(centered ** 3, axis=1) / std ** 3,
        "confiance": probs.max(axis=1),
        "classe_predite": np.array(CLASSES)[probs.argmax(axis=1)],
    })


def simulate(x: np.ndarray, scenario: str, rng: np.random.Generator) -> np.ndarray:
    x = x.copy()
    if scenario == "capteur_bruite":
        n = len(x)
        t = np.linspace(0, 1, N_SAMPLES)
        wander = 0.8 * np.sin(2 * np.pi * 0.7 * t + rng.uniform(0, 6.28, (n, 1)))
        x[:, :N_SAMPLES] += rng.normal(0, 0.35, (n, N_SAMPLES)) + wander
    elif scenario == "tachycardie":
        # Intervalles RR absolus (pre, post) plus courts ; les ratios au rythme local ne bougent pas.
        x[:, N_SAMPLES:N_SAMPLES + 2] *= 0.65
    return x


def run_report(reference: pd.DataFrame, current: pd.DataFrame, out_html: Path) -> dict:
    definition = DataDefinition(numerical_columns=FEATURES[:-1],
                                categorical_columns=["classe_predite"])
    snapshot = Report([DataDriftPreset()]).run(
        Dataset.from_pandas(current, data_definition=definition),
        Dataset.from_pandas(reference, data_definition=definition),
    )
    out_html.parent.mkdir(parents=True, exist_ok=True)
    snapshot.save_html(str(out_html))
    return summarize(snapshot.dict())


def summarize(result: dict) -> dict:
    """Extrait du rapport le nombre de colonnes en dérive et la statistique par colonne."""
    summary: dict = {"colonnes": {}}
    for metric in result.get("metrics", []):
        name = str(metric.get("metric_name", metric.get("metric_id", "")))
        value = metric.get("value")
        if name.startswith("DriftedColumnsCount") and isinstance(value, dict):
            summary["n_colonnes_en_derive"] = int(value.get("count", 0))
            summary["part_colonnes_en_derive"] = float(value.get("share", 0.0))
        elif name.startswith("ValueDrift") and isinstance(value, (int, float)):
            config = metric.get("config", {})
            column = config.get("column") or name.split("column=")[-1].split(",")[0]
            method = str(config.get("method", ""))
            threshold = float(config.get("threshold", 0.05))
            # Evidently choisit le test selon la taille de l'échantillon : p-value (K-S, chi²)
            # pour les petits échantillons -> dérive si p < seuil ; distance (Wasserstein,
            # Jensen-Shannon) pour les grands -> dérive si distance >= seuil.
            is_p_value = "p_value" in method or "p-value" in method
            drifted = value < threshold if is_p_value else value >= threshold
            summary["colonnes"][column] = {"valeur": round(float(value), 4), "methode": method,
                                           "seuil": threshold, "derive": bool(drifted)}
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Rapports de dérive Evidently")
    parser.add_argument("--params", default="params.yaml")
    parser.add_argument("--model-dir", default="models/ecg-cnn-bilstm")
    parser.add_argument("--sample", type=int, default=5000, help="battements par population")
    parser.add_argument("--out", default="reports/drift")
    args = parser.parse_args()
    params = yaml.safe_load(Path(args.params).read_text(encoding="utf-8"))
    d, ml = params["data"], params["mlflow"]
    rng = np.random.default_rng(0)

    model, meta = load_model(Path(args.model_dir))
    x1, _, _ = load_or_prepare("DS1", Path(d["raw_dir"]), Path(d["processed_dir"]))
    x2, _, _ = load_or_prepare("DS2", Path(d["raw_dir"]), Path(d["processed_dir"]))
    pick = lambda x: x[rng.choice(len(x), size=min(args.sample, len(x)), replace=False)]
    reference = describe_beats(pick(x1), model)
    current_base = pick(x2)

    mlflow.set_tracking_uri(os.environ.get("MLFLOW_TRACKING_URI", ml["tracking_uri"]))
    mlflow.set_experiment("ecg-drift")
    results = {}
    for scenario in ("ds2", "capteur_bruite", "tachycardie"):
        current = describe_beats(simulate(current_base, scenario, rng), model)
        html = Path(args.out) / f"drift_{scenario}.html"
        summary = run_report(reference, current, html)
        summary["part_anomalies_predites"] = round(float((current["classe_predite"] != "N").mean()), 4)
        summary["confiance_moyenne"] = round(float(current["confiance"].mean()), 4)
        results[scenario] = summary
        with mlflow.start_run(run_name=f"drift-{scenario}"):
            mlflow.set_tags({"scenario": scenario, "model_version": meta["version"]})
            mlflow.log_metrics({k: v for k, v in summary.items() if isinstance(v, (int, float))})
            mlflow.log_artifact(str(html))
        print(f"{scenario:15s} colonnes en dérive : {summary.get('n_colonnes_en_derive')}/"
              f"{len(FEATURES)}  anomalies prédites : {summary['part_anomalies_predites']:.1%}  "
              f"confiance : {summary['confiance_moyenne']:.3f}")

    reference_stats = {"part_anomalies_predites": round(float((reference["classe_predite"] != "N").mean()), 4),
                       "confiance_moyenne": round(float(reference["confiance"].mean()), 4)}
    out = Path(args.out) / "summary.json"
    out.write_text(json.dumps({"modele": meta["version"], "reference_ds1": reference_stats,
                               "scenarios": results}, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Référence DS1   anomalies prédites : {reference_stats['part_anomalies_predites']:.1%}  "
          f"confiance : {reference_stats['confiance_moyenne']:.3f}")
    print(f"Résumé : {out}")


if __name__ == "__main__":
    main()
