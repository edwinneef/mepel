import pytest

from tools.evaluate_unseen_positioning import apply_labels


def test_evaluation_labels_cannot_overwrite_predictions_or_other_maps():
    result = {"map_id": 42, "sha256": "a" * 64, "predicted_xy": [100, 200]}
    labels = [{"map_id": 42, "sha256": "a" * 64,
               "method": "independent_world_landmarks_and_feet", "truth_xy": [9000, 9000],
               "predicted_xy": [9000, 9000], "independent_truth": True}]
    labelled = apply_labels([result], labels)
    assert labelled[0]["predicted_xy"] == [100, 200]
    assert labelled[0]["truth_xy"] == [9000, 9000]
    assert "truth_xy" not in result
    assert "truth_xy" not in apply_labels([{**result, "map_id": 60}], labels)[0]


@pytest.mark.parametrize("method", ["saved_walk_calibration", "constructed_drawing_coordinates"])
def test_duplicate_or_non_native_labels_refuse(method):
    result = {"map_id": 42, "sha256": "a" * 64, "predicted_xy": None}
    label = {"map_id": 42, "sha256": "a" * 64, "method": method}
    with pytest.raises(ValueError, match="independent"):
        apply_labels([result], [label])
    with pytest.raises(ValueError, match="Duplicate"):
        apply_labels([result], [label, label])
