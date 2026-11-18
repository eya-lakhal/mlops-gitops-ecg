"""Préparation des données MIT-BIH.

Étapes : téléchargement (PhysioNet) -> filtrage passe-bande -> segmentation autour
des pics R -> features RR -> regroupement en classes AAMI -> découpage inter-patient
DS1 (entraînement) / DS2 (test) selon de Chazal et al. (2004).
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import yaml
from scipy.signal import butter, filtfilt

from ecg.constants import AFTER, BEFORE, CLASSES, FS, N_FEATURES, N_RR

# Symboles d'annotation MIT-BIH -> classes AAMI
_SYMBOL_TO_CLASS = {
    **dict.fromkeys(["N", "L", "R", "e", "j"], "N"),
    **dict.fromkeys(["A", "a", "J", "S"], "S"),
    **dict.fromkeys(["V", "E"], "V"),
    "F": "F",
    **dict.fromkeys(["/", "f", "Q"], "Q"),
}
BEAT_SYMBOLS = frozenset(_SYMBOL_TO_CLASS)

# Découpage inter-patient de de Chazal : aucun patient commun entre DS1 et DS2.
# Les enregistrements avec pacemaker (102, 104, 107, 217) sont exclus, comme le recommande l'AAMI.
DS1 = ["101", "106", "108", "109", "112", "114", "115", "116", "118", "119", "122",
       "124", "201", "203", "205", "207", "208", "209", "215", "220", "223", "230"]
DS2 = ["100", "103", "105", "111", "113", "117", "121", "123", "200", "202", "210",
       "212", "213", "214", "219", "221", "222", "228", "231", "232", "233", "234"]


def aami_class(symbol: str) -> str | None:
    """Classe AAMI d'un symbole d'annotation, ou None si ce n'est pas un battement."""
    return _SYMBOL_TO_CLASS.get(symbol)


def bandpass(signal: np.ndarray, fs: int = FS, low: float = 0.5, high: float = 40.0,
             order: int = 3) -> np.ndarray:
    """Retire la dérive de ligne de base (< 0,5 Hz) et le bruit secteur/musculaire (> 40 Hz)."""
    b, a = butter(order, [low, high], btype="band", fs=fs)
    return filtfilt(b, a, signal)


def rr_features(r_peaks: np.ndarray, fs: int = FS, local_window: int = 10) -> np.ndarray:
    """Features de rythme par battement : pre-RR, post-RR et leurs ratios au rythme local.

    Les ratios rendent la feature indépendante de la fréquence cardiaque propre au patient,
    ce qui est essentiel pour reconnaître un battement prématuré (classe S) en inter-patient.
    Le premier et le dernier battement n'ont pas de voisins : leurs features valent NaN.
    """
    r = np.asarray(r_peaks, dtype=np.float64)
    rr = np.diff(r) / fs  # rr[k] = intervalle entre le battement k et k+1
    feats = np.full((len(r), N_RR), np.nan, dtype=np.float32)
    for i in range(1, len(r) - 1):
        pre, post = rr[i - 1], rr[i]
        local = rr[max(0, i - local_window):i].mean()
        feats[i] = (pre, post, pre / local, post / local)
    return feats


def extract_beats(signal: np.ndarray, r_peaks: np.ndarray, symbols: list[str],
                  fs: int = FS) -> tuple[np.ndarray, np.ndarray]:
    """Découpe une fenêtre de N_SAMPLES points autour de chaque pic R.

    Retourne X de forme (n, N_FEATURES) = [battement normalisé | 4 features RR] et y (indices
    de classe). Les battements hors classes retenues ou trop près des bords sont ignorés.
    """
    feats = rr_features(r_peaks, fs)
    xs, ys = [], []
    last = len(r_peaks) - 1
    for i, (r, symbol) in enumerate(zip(r_peaks, symbols)):
        cls = aami_class(symbol)
        if cls not in CLASSES or i == 0 or i == last:
            continue
        start, end = int(r) - BEFORE, int(r) + AFTER
        if start < 0 or end > len(signal):
            continue
        beat = signal[start:end]
        beat = (beat - beat.mean()) / (beat.std() + 1e-6)  # normalisation par battement
        xs.append(np.concatenate([beat, feats[i]]))
        ys.append(CLASSES.index(cls))
    x = np.asarray(xs, dtype=np.float32).reshape(-1, N_FEATURES)
    return x, np.asarray(ys, dtype=np.int64)


def download(raw_dir: Path) -> None:
    """Télécharge les enregistrements MIT-BIH utiles depuis PhysioNet (~100 Mo), si absents."""
    import wfdb

    records = DS1 + DS2
    missing = [r for r in records
               if not all((raw_dir / f"{r}.{ext}").exists() for ext in ("hea", "dat", "atr"))]
    if not missing:
        print(f"MIT-BIH déjà présent dans {raw_dir}")
        return
    raw_dir.mkdir(parents=True, exist_ok=True)
    print(f"Téléchargement de {len(missing)} enregistrements MIT-BIH vers {raw_dir} ...")
    wfdb.dl_database("mitdb", dl_dir=str(raw_dir), records=missing)


def load_record(record: str, raw_dir: Path) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Lit la dérivation MLII filtrée et les annotations de battements d'un enregistrement."""
    import wfdb

    path = str(raw_dir / record)
    rec = wfdb.rdrecord(path)
    channel = rec.sig_name.index("MLII") if "MLII" in rec.sig_name else 0
    signal = bandpass(rec.p_signal[:, channel])
    ann = wfdb.rdann(path, "atr")
    keep = [k for k, s in enumerate(ann.symbol) if s in BEAT_SYMBOLS]
    return signal, ann.sample[keep], [ann.symbol[k] for k in keep]


def build_dataset(records: list[str], raw_dir: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Construit X, y et l'identifiant d'enregistrement (patient) de chaque battement."""
    xs, ys, recs = [], [], []
    for record in records:
        x, y = extract_beats(*load_record(record, raw_dir))
        xs.append(x)
        ys.append(y)
        recs.append(np.full(len(y), record))
    return np.concatenate(xs), np.concatenate(ys), np.concatenate(recs)


def load_or_prepare(split: str, raw_dir: Path, processed_dir: Path):
    """Charge DS1 ou DS2 depuis le cache .npz, ou le construit au premier appel."""
    cache = processed_dir / f"{split.lower()}.npz"
    if not cache.exists():
        download(raw_dir)
        records = DS1 if split.upper() == "DS1" else DS2
        x, y, recs = build_dataset(records, raw_dir)
        processed_dir.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(cache, x=x, y=y, records=recs)
    data = np.load(cache)
    return data["x"], data["y"], data["records"]


def describe(name: str, y: np.ndarray) -> str:
    counts = np.bincount(y, minlength=len(CLASSES))
    detail = ", ".join(f"{c}={n}" for c, n in zip(CLASSES, counts))
    return f"{name}: {len(y)} battements ({detail})"


def main() -> None:
    parser = argparse.ArgumentParser(description="Prépare les jeux DS1/DS2 de MIT-BIH")
    parser.add_argument("--params", default="params.yaml")
    args = parser.parse_args()
    cfg = yaml.safe_load(Path(args.params).read_text(encoding="utf-8"))["data"]
    raw_dir, processed_dir = Path(cfg["raw_dir"]), Path(cfg["processed_dir"])
    for split in ("DS1", "DS2"):
        _, y, _ = load_or_prepare(split, raw_dir, processed_dir)
        print(describe(split, y))


if __name__ == "__main__":
    main()
