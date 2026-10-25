import hashlib
import json

import cv2
import numpy as np
import pytest

from maplebot.catalog import import_catalog, import_map_catalog, monster_ids_through_level
from maplebot.config import PerceptionConfig
from maplebot.perception import TemplateDetector


def test_level_selection_includes_boundary_and_excludes_bosses_and_unknown_levels():
    monsters = [
        {"id": 1, "level": 1, "isBoss": False},
        {"id": 2, "level": 50, "isBoss": False},
        {"id": 3, "level": 51, "isBoss": False},
        {"id": 4, "level": 20, "isBoss": True},
        {"id": 5, "isBoss": False},
        {"id": 6, "level": 0, "isBoss": False},
    ]
    assert monster_ids_through_level(50, fetch=lambda url: json.dumps(monsters).encode()) == [1, 2]


def test_map_import_keeps_only_titles_and_monster_ids_and_reuses_cache(tmp_path):
    index = [{"id": 1, "name": "Training", "streetName": "Road"}]

    def fetch(url):
        return json.dumps(
            index
            if url.endswith("/map")
            else {
                "mobs": [{"id": 100100, "x": 123}, {"id": 100100, "x": 456}],
                "portals": [{"x": 999}],
            }
        ).encode()

    result = import_map_catalog(tmp_path, fetch=fetch)
    assert result == {"maps": 1, "warnings": []}
    saved = json.loads((tmp_path / "catalog/maps.json").read_text())
    assert saved == [{**index[0], "monsters": [100100]}]

    def cached(url):
        assert url.endswith("/map")
        return json.dumps(index).encode()

    assert import_map_catalog(tmp_path, fetch=cached)["maps"] == 1


def animated_sprite(count=2):
    frames = []
    for index in range(count):
        offset = (index * 2) % 8
        image = np.zeros((32, 40, 4), dtype=np.uint8)
        cv2.ellipse(image, (20, 16), (12, 10), 0, 0, 360, (50 + index, 140, 230, 255), -1)
        cv2.circle(image, (16 + offset, 14), 3, (20, 20, 20, 255), -1)
        cv2.rectangle(image, (21, 18), (28, 20), (245, 245, 245, 255), -1)
        frames.append(image)
    animation = cv2.Animation()
    animation.frames = frames
    animation.durations = np.full(count, 100, dtype=np.int32)
    ok, encoded = cv2.imencodeanimation(".png", animation)
    assert ok
    return encoded.tobytes()


def test_imports_every_pose_including_frames_after_32(tmp_path):
    payload = animated_sprite(40)

    def fetch(url):
        return b'{"name":"Test Mob"}' if url.endswith("/name") else payload

    result = import_catalog(tmp_path, [100100], fetch=fetch)
    manifest = json.loads((tmp_path / "catalog" / "manifest.json").read_text())
    assert result["frames"] == 80
    for action in ("stand", "move"):
        assert sorted(
            entry["frame"] for entry in manifest["entries"] if entry["animation"] == action
        ) == list(range(40))


def test_imports_jump_and_hit_references_for_visible_combat_poses(tmp_path):
    payload = animated_sprite()

    def fetch(url):
        return b'{"name":"Test Mob"}' if url.endswith("/name") else payload

    import_catalog(tmp_path, [100100], fetch=fetch, actions=("stand", "move", "jump", "hit1"))
    manifest = json.loads((tmp_path / "catalog/manifest.json").read_text())
    assert {entry["animation"] for entry in manifest["entries"]} == {
        "stand",
        "move",
        "jump",
        "hit1",
    }


def test_imports_animation_frames_and_provenance_without_gameplay_data(tmp_path):
    calls = []
    payload = animated_sprite()

    def fetch(url):
        calls.append(url)
        return (
            json.dumps({"name": "Test Mob", "id": 100100}).encode()
            if url.endswith("/name")
            else payload
        )

    result = import_catalog(tmp_path, [100100], fetch=fetch)
    assert result["species"] == 1
    assert result["frames"] == 4
    assert all("/name" in url or "/mob/animated/" in url for url in calls)
    manifest = json.loads((tmp_path / "catalog" / "manifest.json").read_text())
    assert len(manifest["entries"]) == 4
    for entry in manifest["entries"]:
        path = tmp_path / "catalog" / entry["file"]
        image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        assert image.shape[2] == 4
        assert np.any(image[:, :, 3] == 0)
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"]
        assert entry["name"] == "Test Mob"
        assert not {"hp", "spawns", "maps", "drops", "coordinates"}.intersection(entry)


def test_reimport_uses_cached_images_and_preserves_manual_templates(tmp_path):
    manual = tmp_path / "monster" / "custom.png"
    manual.parent.mkdir()
    manual.write_bytes(b"user-owned example")
    payload = animated_sprite()

    def fetch(url):
        return b'{"name":"Test Mob"}' if url.endswith("/name") else payload

    first = import_catalog(tmp_path, [100100], fetch=fetch)

    def offline(url):
        raise AssertionError(f"Unexpected second network request: {url}")

    second = import_catalog(tmp_path, [100100], fetch=offline)
    assert second["frames"] == first["frames"]
    assert manual.read_bytes() == b"user-owned example"


def test_missing_move_animation_keeps_valid_stand_frames(tmp_path):
    payload = animated_sprite()

    def fetch(url):
        if url.endswith("/name"):
            return b'{"name":"Stationary mob"}'
        if "/move?" in url:
            raise OSError("Animation unavailable")
        return payload

    result = import_catalog(tmp_path, [130100], fetch=fetch)
    assert result["species"] == 1
    assert result["frames"] == 2
    assert result["warnings"]


def test_invalid_images_are_not_published_as_templates(tmp_path):
    def fetch(url):
        return b'{"name":"Test Mob"}' if url.endswith("/name") else b"not an image"

    with pytest.raises(ValueError, match="No usable"):
        import_catalog(tmp_path, [100100], fetch=fetch)
    assert not list((tmp_path / "catalog" / "monster").glob("*.png"))


def test_catalog_detects_offline_without_requesting_any_network(monkeypatch, tmp_path):
    payload = animated_sprite()

    def fetch(url):
        return b'{"name":"Test Mob"}' if url.endswith("/name") else payload

    import_catalog(tmp_path, [100100], fetch=fetch)

    def forbidden(*args, **kwargs):
        raise AssertionError("Live detection must not request network resources")

    monkeypatch.setattr("urllib.request.urlopen", forbidden)
    detector = TemplateDetector(tmp_path, PerceptionConfig())
    assert detector.catalog_info["species"] == 1
    assert detector.catalog_info["frames"] == 4
    frame = np.full((160, 220, 3), 70, dtype=np.uint8)
    reference = cv2.imread(
        str(next((tmp_path / "catalog" / "monster").glob("*.png"))), cv2.IMREAD_UNCHANGED
    )
    height, width = reference.shape[:2]
    target = frame[60 : 60 + height, 100 : 100 + width]
    target[reference[:, :, 3] == 255] = reference[:, :, :3][reference[:, :, 3] == 255]
    result = detector.detect(frame)
    assert any(item.confidence >= 0.9 and "Test Mob" in item.template for item in result.monsters)


def test_catalog_hash_mismatch_is_rejected(tmp_path):
    payload = animated_sprite()

    def fetch(url):
        return b'{"name":"Test Mob"}' if url.endswith("/name") else payload

    import_catalog(tmp_path, [100100], fetch=fetch)
    path = next((tmp_path / "catalog" / "monster").glob("*.png"))
    image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    image[8, 10, 0] ^= 255
    cv2.imwrite(str(path), image)
    with pytest.raises(ValueError, match="hash mismatch"):
        TemplateDetector(tmp_path, PerceptionConfig())


def test_unpublished_catalog_files_do_not_prevent_loading(tmp_path):
    payload = animated_sprite()
    import_catalog(
        tmp_path,
        [100100],
        fetch=lambda url: b'{"name":"Test Mob"}' if url.endswith("/name") else payload,
    )
    (tmp_path / "catalog/monster/unpublished.png").write_bytes(b"invalid image")
    detector = TemplateDetector(tmp_path, PerceptionConfig())
    assert detector.catalog_info["frames"] == 4
    detector.map_filter.close()
