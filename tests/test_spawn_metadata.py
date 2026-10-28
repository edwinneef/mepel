import copy
import json

import pytest

from maplebot.spawn_metadata import load_dataset, resolve_species, validate_dataset


@pytest.fixture
def dataset():
    return {
        "schemaVersion": 1, "sourceId": "classic", "revision": "r1",
        "provenance": {"url": "https://example.org/maps/001", "sha256": "a" * 64,
                       "asOf": "2026-10-28"},
        "species": {"snail": {"sourceSpeciesId": "classic-snail", "spriteName": "Snail"}},
        "maps": [{"mapId": "001", "street": "Road", "title": "Forest III",
                  "species": ["snail"]}],
    }


def test_roundtrip_preserves_source_revision_and_leading_zeroes(tmp_path, dataset):
    path = tmp_path / "reference.json"
    path.write_text(json.dumps(dataset))
    assert load_dataset(path) == dataset
    assert path.read_text() == json.dumps(dataset)


def test_groups_include_multiple_asset_ids_without_matching_source_ids(dataset):
    groups, missing = resolve_species(dataset, [
        {"id": 10, "name": "Snail"}, {"id": 20, "name": "Snail"},
        {"id": 30, "name": "Blue Snail"},
    ])
    assert groups == {"snail": {10, 20}}
    assert missing == []
    assert resolve_species(dataset, [{"id": "classic-snail", "name": "Wrong"}]) == (
        {"snail": set()}, ["snail"])


@pytest.mark.parametrize("change", [
    lambda d: d.update(schemaVersion=2),
    lambda d: d.update(sourceId="../classic"),
    lambda d: d["provenance"].update(sha256="invalid"),
    lambda d: d["provenance"].update(url="file:///local"),
    lambda d: d["provenance"].update(asOf="not-a-date"),
    lambda d: d["maps"].append(copy.deepcopy(d["maps"][0])),
    lambda d: d["maps"][0].update(mapId=1),
    lambda d: d["maps"][0].update(species=["unknown"]),
    lambda d: d["species"].update(other=copy.deepcopy(d["species"]["snail"])),
])
def test_rejects_invalid_identity_provenance_and_crosswalk(dataset, change):
    change(dataset)
    with pytest.raises(ValueError):
        validate_dataset(dataset)
