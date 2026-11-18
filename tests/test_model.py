import numpy as np
import torch

from ecg.constants import CLASSES, N_FEATURES
from ecg.model import CnnBiLstm
import pytest

from ecg.train import apply_overrides, class_weights, flatten


def test_forward_output_shape():
    model = CnnBiLstm()
    logits = model(torch.randn(8, N_FEATURES))
    assert logits.shape == (8, len(CLASSES))


def test_model_can_overfit_tiny_batch():
    """Sanity check : le modèle doit pouvoir mémoriser 16 exemples."""
    torch.manual_seed(0)
    model = CnnBiLstm(dropout=0.0)
    x, y = torch.randn(16, N_FEATURES), torch.arange(16) % len(CLASSES)
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-2)
    for _ in range(200):
        optimizer.zero_grad()
        loss = torch.nn.functional.cross_entropy(model(x), y)
        loss.backward()
        optimizer.step()
    assert loss.item() < 0.1


def test_class_weights_favour_rare_classes():
    y = np.array([0] * 900 + [1] * 50 + [2] * 40 + [3] * 10)
    w = class_weights(y, 4, power=0.5)
    assert w[3] > w[1] > w[0]
    assert class_weights(y, 4, power=0.0).allclose(torch.ones(4))


def test_apply_overrides_parses_yaml_values():
    params = {"train": {"lr": 0.001, "epochs": 20}, "data": {"val_records": ["101"]}}
    apply_overrides(params, ["train.lr=0.0005", "data.val_records=['118', '223']"])
    assert params["train"]["lr"] == 0.0005
    assert params["data"]["val_records"] == ["118", "223"]
    with pytest.raises(KeyError):
        apply_overrides(params, ["train.lrr=0.1"])  # faute de frappe détectée


def test_flatten_params():
    assert flatten({"a": {"b": 1, "c": [1, 2]}}) == {"a.b": "1", "a.c": "1,2"}
