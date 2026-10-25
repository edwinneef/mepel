import json

import numpy as np

from maplebot.map_filter import MapFilter


def make_filter(tmp_path):
    root = tmp_path / "catalog"
    root.mkdir()
    (root / "maps.json").write_text(
        json.dumps(
            [
                {
                    "id": 1,
                    "streetName": "Kerning City Subway",
                    "name": "Line 1 <Area 1>",
                    "monsters": [1210103],
                },
                {
                    "id": 2,
                    "streetName": "Kerning City Subway",
                    "name": "Line 1 <Area 1>",
                    "monsters": [100100],
                },
                {
                    "id": 3,
                    "streetName": "Victoria Road",
                    "name": "Subway Ticketing Booth",
                    "monsters": [],
                },
            ]
        )
    )
    return MapFilter(
        tmp_path,
        [
            {"id": 1210103, "name": "Bubbling"},
            {"id": 100100, "name": "Snail"},
        ],
    )


def test_matching_uses_full_title_and_unions_identical_map_names(tmp_path):
    router = make_filter(tmp_path)
    try:
        assert router.match("mini map Kerning City Subway Line 1 <Area 1>") == (
            "Line 1 <Area 1>",
            {"Bubbling", "Snail"},
        )
        assert router.match("Kerning City Subway Line 1 <Area") == (None, None)
        assert router.match("Victoria Road : Subway Ticketing Booth") == (
            "Subway Ticketing Booth",
            set(),
        )
    finally:
        router.close()


def test_changed_or_unreadable_title_falls_back_to_full_catalog(monkeypatch, tmp_path):
    router = make_filter(tmp_path)
    monkeypatch.setattr(
        "maplebot.map_filter.read_title", lambda image: "Kerning City Subway Line 1 <Area 1>"
    )
    image = np.zeros((100, 350, 3), dtype=np.uint8)
    try:
        assert router.select(image) is None
        router.pending.result(timeout=3)
        assert router.select(image) == {"Bubbling", "Snail"}
        monkeypatch.setattr("maplebot.map_filter.read_title", lambda image: "Loading...")
        image[:19] = 100
        assert router.select(image) is None
        router.pending.result(timeout=3)
        assert router.select(image) is None
        assert router.title is None
    finally:
        router.close()


def test_unavailable_ocr_keeps_full_catalog(monkeypatch, tmp_path):
    router = make_filter(tmp_path)

    def unavailable(image):
        raise RuntimeError("OCR unavailable")

    monkeypatch.setattr("maplebot.map_filter.read_title", unavailable)
    image = np.zeros((100, 350, 3), dtype=np.uint8)
    try:
        router.select(image)
        try:
            router.pending.result(timeout=3)
        except RuntimeError:
            pass
        assert router.select(image) is None
        assert router.error == "OCR unavailable"
    finally:
        router.close()


def test_ocr_typo_requires_unique_match_and_preserves_map_numbers(tmp_path):
    router = make_filter(tmp_path)
    router.profiles.extend(
        [
            {
                "streetName": "Hidden Street",
                "name": "The Blue Mushroom Forest",
                "monsters": [100100],
            },
            {"streetName": "Hidden Street", "name": "대기실", "monsters": [1210103]},
        ]
    )
    try:
        assert router.match("Hidden Street The Blue Mushrooln Forest") == (
            "The Blue Mushroom Forest",
            {"Snail"},
        )
        assert router.match("Hidden Street Unrecognized Forest") == (None, None)
        assert router.match("Kerning City Subway Line 1 <Area 2>") == (None, None)
        router.profiles.append(
            {"streetName": "Hidden Street", "name": "The Blue Mushroom Forests", "monsters": []}
        )
        assert router.match("Hidden Street The Blue Mushrooln Forest") == (None, None)
    finally:
        router.close()
