import numpy as np

from ecg.constants import CLASSES, N_FEATURES, N_SAMPLES
from ecg.data import DS1, DS2, aami_class, extract_beats, rr_features


def test_aami_mapping():
    assert aami_class("L") == "N"
    assert aami_class("A") == "S"
    assert aami_class("E") == "V"
    assert aami_class("F") == "F"
    assert aami_class("/") == "Q"
    assert aami_class("+") is None  # changement de rythme : pas un battement


def test_inter_patient_split_has_no_overlap():
    assert not set(DS1) & set(DS2)
    assert len(DS1) == len(DS2) == 22


def test_rr_features_on_regular_rhythm():
    r_peaks = np.arange(0, 360 * 10, 360)  # un battement par seconde
    feats = rr_features(r_peaks, fs=360)
    assert np.isnan(feats[0]).all() and np.isnan(feats[-1]).all()
    np.testing.assert_allclose(feats[5], [1.0, 1.0, 1.0, 1.0])


def test_rr_features_detect_premature_beat():
    r_peaks = np.array([0, 360, 720, 1080, 1260, 1800, 2160])  # 5e battement en avance
    feats = rr_features(r_peaks, fs=360)
    assert feats[4, 2] < 0.6  # pre-RR très court par rapport au rythme local
    assert feats[4, 3] > 1.4  # pause compensatoire après


def test_extract_beats_shapes_and_filtering():
    signal = np.sin(np.linspace(0, 60, 360 * 10))
    r_peaks = np.arange(180, 360 * 10 - 180, 360)  # 9 battements
    symbols = ["N"] * len(r_peaks)
    symbols[3], symbols[4] = "V", "Q"
    x, y = extract_beats(signal, r_peaks, symbols, fs=360)
    # premier et dernier exclus (pas de RR complet), Q exclu
    assert x.shape == (len(r_peaks) - 3, N_FEATURES)
    assert x.dtype == np.float32
    assert CLASSES.index("V") in y
    np.testing.assert_allclose(x[:, :N_SAMPLES].mean(axis=1), 0.0, atol=1e-5)
