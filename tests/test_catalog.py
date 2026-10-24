import hashlib
import json

import cv2
import numpy as np
import pytest

from maplebot.catalog import import_catalog
from maplebot.config import PerceptionConfig
from maplebot.perception import TemplateDetector


def animated_sprite():
    frames = []
    for offset in (0, 2):
        image = np.zeros((32, 40, 4), dtype=np.uint8)
        cv2.ellipse(image, (20, 16), (12, 10), 0, 0, 360, (50, 140, 230, 255), -1)
        cv2.circle(image, (16 + offset, 14), 3, (20, 20, 20, 255), -1)
        cv2.rectangle(image, (21, 18), (28, 20), (245, 245, 245, 255), -1)
        frames.append(image)
    animation = cv2.Animation()
    animation.frames = frames
    animation.durations = np.array([100, 100], dtype=np.int32)
    ok, encoded = cv2.imencodeanimation(".png", animation)
    assert ok
    return encoded.tobytes()


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
