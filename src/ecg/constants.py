"""Constantes partagées entre l'entraînement et l'API (sans dépendance lourde)."""

FS = 360  # fréquence d'échantillonnage de MIT-BIH (Hz)
BEFORE = 90  # échantillons avant le pic R (0,25 s)
AFTER = 166  # échantillons après le pic R (~0,46 s)
N_SAMPLES = BEFORE + AFTER  # 256 points par battement
N_RR = 4  # pre-RR, post-RR, pre-RR/local, post-RR/local
N_FEATURES = N_SAMPLES + N_RR  # entrée du modèle : 260 valeurs

# Classes AAMI retenues (la classe Q, quasi absente hors enregistrements stimulés, est exclue)
CLASSES = ["N", "S", "V", "F"]
CLASS_DESCRIPTIONS = {
    "N": "Battement normal (ou bloc de branche)",
    "S": "Ectopique supraventriculaire",
    "V": "Ectopique ventriculaire",
    "F": "Fusion ventriculaire/normal",
}
