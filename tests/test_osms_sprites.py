import hashlib
import json

import cv2
import numpy as np
import pytest

from maplebot.config import PerceptionConfig
from maplebot.osms_sprites import import_sprites
from maplebot.perception import TemplateDetector


def setup_source(tmp_path):
    names = ["Super Mob", "Ultra Mob"]
    data = {"schemaVersion": 1, "sourceId": "osms-classic", "revision": "a" * 40,
            "provenance": {"url": "https://example.org", "sha256": "b" * 64,
                           "asOf": "2026-10-28"},
            "species": {str(i): {"sourceSpeciesId": str(i), "spriteName": name}
                        for i, name in enumerate(names, 1)},
            "maps": [{"mapId": str(i), "street": "Road", "title": name, "species": [str(i)]}
                     for i, name in enumerate(names, 1)]}
    path = tmp_path / "dataset.json"
    path.write_text(json.dumps(data))
    image = np.zeros((24, 24, 4), np.uint8)
    image[3:21, 3:21] = (30, 180, 200, 255)
    image[8:13, 8:13] = (230, 20, 40, 255)
    animation = cv2.Animation()
    animation.frames = [image, np.flip(image, axis=1).copy()]
    animation.durations = np.array([100, 100], np.int32)
    ok, encoded = cv2.imencodeanimation(".webp", animation)
    assert ok
    records = {"monsters": [{"id": i, "name": name, "gifs": {"move": "c" * 32}}
                            for i, name in enumerate(names, 1)]}
    def fetch(url):
        return json.dumps(records).encode() if url.endswith("monsters.json") else encoded.tobytes()
    return path, fetch, records


def test_dry_run_preservation_idempotency_and_shared_labels(tmp_path):
    dataset, fetch, _ = setup_source(tmp_path)
    root = tmp_path / "templates"
    report = import_sprites(root, dataset, dry_run=True, fetch=fetch)
    assert report["names"] == ["Super Mob", "Ultra Mob"]
    assert report["assets"] == 1 and report["frames"] == 4
    assert not root.exists()
    root.joinpath("catalog").mkdir(parents=True)
    manifest = root / "catalog/manifest.json"
    old = b'{"format":1,"source":"preserve","entries":[]}'
    manifest.write_bytes(old)
    import_sprites(root, dataset, fetch=fetch)
    saved = json.loads(manifest.read_text())
    assert saved["source"] == "preserve"
    assert next(manifest.parent.glob("*.bak")).read_bytes() == old
    for entry in saved["entries"]:
        assert entry["id"] < -1_000_000_000
        content = (manifest.parent / entry["file"]).read_bytes()
        assert hashlib.sha256(content).hexdigest() == entry["sha256"]
    assert not import_sprites(root, dataset, fetch=lambda _: pytest.fail("network"))["changed"]
    detector = TemplateDetector(root, PerceptionConfig())
    try:
        labels = {t.name.split(":")[1] for t in detector.templates if t.name.startswith("catalog:")}
        assert labels == {"Super Mob", "Ultra Mob"}
        # Each map's filter must retain actual templates, including identical pixels.
        for label in labels:
            assert any(t.name.startswith(f"catalog:{label}:") for t in detector.templates)
    finally:
        detector.map_filter.close()
        detector.pool.shutdown(wait=True)


def test_failed_animation_does_not_modify_catalog(tmp_path):
    dataset, fetch, _ = setup_source(tmp_path)
    root = tmp_path / "templates"
    with pytest.raises((ValueError, cv2.error)):
        import_sprites(
            root, dataset, fetch=lambda u: fetch(u) if u.endswith(".json") else b"broken"
        )
    assert not root.exists()


def test_name_mismatch_and_unsafe_hash_fail_without_writes(tmp_path):
    dataset, fetch, records = setup_source(tmp_path)
    records["monsters"][0]["gifs"]["move"] = "../../untrusted"
    with pytest.raises(ValueError, match="image hash"):
        import_sprites(tmp_path / "templates", dataset, fetch=fetch)
    records["monsters"][0]["name"] = "Wrong"
    with pytest.raises(ValueError, match="differs"):
        import_sprites(tmp_path / "templates", dataset, fetch=fetch)
    assert not (tmp_path / "templates").exists()
