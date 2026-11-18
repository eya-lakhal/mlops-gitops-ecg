"""Extrait quelques vrais battements de DS2 (patients de test) vers samples/beats.json.

Ce fichier sert d'exemple de requête pour l'API (curl, Swagger, k6). Le champ
« expected » est ignoré par l'API ; il permet de comparer à la vérité terrain.
Données : MIT-BIH Arrhythmia Database, PhysioNet (licence ODC-By 1.0).
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from ecg.constants import CLASSES

PER_CLASS = 2


def main() -> None:
    data = np.load(Path("data/processed/ds2.npz"))
    x, y = data["x"], data["y"]
    rng = np.random.default_rng(0)
    beats, expected = [], []
    for k, cls in enumerate(CLASSES):
        for i in rng.choice(np.flatnonzero(y == k), size=PER_CLASS, replace=False):
            beats.append([round(float(v), 5) for v in x[i]])
            expected.append(cls)
    out = Path("samples/beats.json")
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"beats": beats, "expected": expected}), encoding="utf-8")
    print(f"{len(beats)} battements écrits dans {out} : {expected}")


if __name__ == "__main__":
    main()
