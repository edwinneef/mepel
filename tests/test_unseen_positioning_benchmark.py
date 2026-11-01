import copy
import json
from pathlib import Path

import pytest

from tools.unseen_positioning_benchmark import assess, load_contract

CONTRACT = Path(__file__).parent / "fixtures" / "unseen-positioning-benchmark.json"


def samples(contract):
    return [{"map_id": key, "truth_xy": [100, 200], "predicted_xy": [101, 201],
             "independent_truth": True, "source_verified": True, "label_uncertainty_px": 2,
             "observable": True} for key in contract["evaluation_maps"] for _ in range(10)]


def test_frozen_contract_keeps_entire_maps_out_of_development(tmp_path):
    contract = load_contract(CONTRACT)
    assert set(contract["development_maps"]).isdisjoint(contract["evaluation_maps"])
    bad = copy.deepcopy(contract)
    bad["development_maps"].append(bad["evaluation_maps"][0])
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(bad))
    with pytest.raises(ValueError, match="disjoint"):
        load_contract(path)


def test_refusing_everything_or_missing_maps_cannot_pass():
    contract = load_contract(CONTRACT)
    rows = samples(contract)
    assert assess(contract, rows)["passed"]
    for row in rows:
        row["predicted_xy"] = None
    assert not assess(contract, rows)["passed"]
    assert not assess(contract, [])["passed"]


@pytest.mark.parametrize("fault", ["truth", "source", "wrong", "ambiguous", "x-only"])
def test_nonindependent_truth_or_false_precision_cannot_pass(fault):
    contract = load_contract(CONTRACT)
    rows = samples(contract)
    for row in rows:
        if fault == "truth":
            row["independent_truth"] = False
        elif fault == "source":
            row["source_verified"] = False
        elif fault == "wrong":
            row["predicted_xy"] = [120, 200]
        elif fault == "ambiguous":
            row["observable"] = False
        else:
            row["predicted_xy"] = [101]
    assert not assess(contract, rows)["passed"]
