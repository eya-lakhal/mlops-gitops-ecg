"""Modèle CNN-BiLSTM pour la classification de battements ECG."""

from __future__ import annotations

import torch
from torch import nn

from ecg.constants import CLASSES, N_RR, N_SAMPLES


class CnnBiLstm(nn.Module):
    """CNN 1D (formes locales : QRS, onde P) + BiLSTM (contexte temporel) + features RR.

    Entrée : tenseur (batch, 260) = 256 points du battement suivis de 4 features RR.
    Garder une entrée « à plat » simplifie la signature MLflow et le contrat de l'API.
    Sortie : logits (batch, n_classes).
    """

    def __init__(self, n_classes: int = len(CLASSES), conv_channels: tuple[int, ...] = (32, 64),
                 lstm_hidden: int = 64, dropout: float = 0.3) -> None:
        super().__init__()
        layers: list[nn.Module] = []
        in_ch = 1
        for i, out_ch in enumerate(conv_channels):
            kernel = 7 if i == 0 else 5
            layers += [
                nn.Conv1d(in_ch, out_ch, kernel_size=kernel, padding=kernel // 2),
                nn.BatchNorm1d(out_ch),
                nn.ReLU(),
                nn.MaxPool1d(2),
            ]
            in_ch = out_ch
        self.cnn = nn.Sequential(*layers)
        self.lstm = nn.LSTM(in_ch, lstm_hidden, batch_first=True, bidirectional=True)
        self.head = nn.Sequential(
            nn.Linear(2 * lstm_hidden + N_RR, 64),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(64, n_classes),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        signal = x[:, :N_SAMPLES].unsqueeze(1)  # (B, 1, 256)
        rr = x[:, N_SAMPLES:]  # (B, 4)
        h = self.cnn(signal).permute(0, 2, 1)  # (B, 64 pas de temps, C)
        h, _ = self.lstm(h)  # (B, T, 2*hidden)
        pooled = h.mean(dim=1)  # moyenne temporelle
        return self.head(torch.cat([pooled, rr], dim=1))
