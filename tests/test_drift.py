import numpy as np
import pandas as pd

from ecg.constants import CLASSES, N_FEATURES, N_SAMPLES
from ecg.drift import FEATURES, describe_beats, run_report, simulate
from ecg.model import CnnBiLstm


def beats(n, seed=0):
    rng = np.random.default_rng(seed)
    x = rng.normal(size=(n, N_FEATURES)).astype(np.float32)
    x[:, N_SAMPLES:] = np.abs(x[:, N_SAMPLES:]) + 0.5  # intervalles RR positifs
    return x


def test_describe_beats_produces_expected_columns():
    df = describe_beats(beats(20), CnnBiLstm().eval())
    assert list(df.columns) == FEATURES
    assert len(df) == 20
    assert set(df["classe_predite"]) <= set(CLASSES)
    assert df["confiance"].between(0, 1).all()


def test_simulated_tachycardia_shortens_rr_only():
    x = beats(10)
    out = simulate(x, "tachycardie", np.random.default_rng(0))
    np.testing.assert_allclose(out[:, N_SAMPLES:N_SAMPLES + 2], x[:, N_SAMPLES:N_SAMPLES + 2] * 0.65,
                               rtol=1e-6)
    np.testing.assert_array_equal(out[:, :N_SAMPLES], x[:, :N_SAMPLES])
    np.testing.assert_array_equal(out[:, N_SAMPLES + 2:], x[:, N_SAMPLES + 2:])


def test_report_detects_obvious_drift(tmp_path):
    rng = np.random.default_rng(0)
    ref = pd.DataFrame({c: rng.normal(size=300) for c in FEATURES[:-1]})
    ref["classe_predite"] = "N"
    cur = ref.copy()
    cur["energie_hf"] += 5  # décalage massif d'une seule colonne
    summary = run_report(ref, cur, tmp_path / "drift.html")
    assert (tmp_path / "drift.html").exists()
    assert summary["n_colonnes_en_derive"] == 1
    assert summary["colonnes"]["energie_hf"]["derive"] is True
    assert summary["colonnes"]["rr_pre"]["derive"] is False
