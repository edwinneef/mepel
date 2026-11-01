import copy
import json
import struct
import subprocess
import zlib
from pathlib import Path

import cv2
import numpy as np
import pytest

from tools import export_classic_assets as exporter


def write_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


@pytest.fixture
def inputs(tmp_path):
    root = tmp_path / "copies"
    rows = []
    for name in sorted(exporter.REQUIRED):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"tiny fixture, never parsed as an installed archive")
        rows.append({"relative": name, "copy": str(path), "original": str(tmp_path / "installed"
                     / name), "sha256": exporter.digest(path), "bytes": path.stat().st_size})
    receipt = tmp_path / "receipt.json"
    write_json(receipt, rows)
    return root, receipt, rows


def canvas(width, height, props=None):
    return {"type": "canvas", "width": width, "height": height,
            "format": 1, "properties": props or {}}


def bundle(path):
    path.mkdir()
    minimap_link = "Map/Map/Map0/_Canvas/000000060.img/miniMap/canvas"
    marker_link = "Map/_Canvas/MapHelper.img/minimap/user"
    original_map = canvas(1, 1, {"_outlink": minimap_link})
    original_marker = canvas(1, 1, {"_outlink": marker_link,
                                     "origin": {"type": "vector", "x": 6, "y": 6}})
    source = {"schema": 1, "map_id": "000000060", "archives": [],
              "raw": {"info": {"version": 10}, "foothold": {"1": {"0": {
                  str(i): {"x1": i, "y1": 0, "x2": i + 1, "y2": 0,
                           "prev": i - 1, "next": i + 1, "piece": -1, "custom": 8}
                  for i in range(205)}}}, "ladderRope": {
                      str(i): {"x": i, "y1": 0, "y2": 10, "l": 1} for i in range(7)},
                  "portal": {str(i): {"pn": f"sp{i}", "pt": 0, "x": i, "y": 0,
                                      "tm": 999999999} for i in range(10)},
                  "miniMap": {"centerX": 652, "centerY": 1505, "mag": 4,
                              "canvas": original_map}}, "marker": original_marker}
    for key, name, width, height, archive, image, prop, original, target in (
        ("minimap_canvas", "minimap-canvas", 295, 138, "Map/Map/Map0/Map0_000.wz",
         "000000060.img", "miniMap/canvas", original_map,
         "Map/Map/Map0/_Canvas/_Canvas_000.wz"),
        ("player_marker", "player-marker", 12, 12, "Map/Map_000.wz", "MapHelper.img",
         "minimap/user", original_marker, "Map/_Canvas/_Canvas_000.wz"),
    ):
        packed = struct.pack("<H", 0x8421) * width * height
        # WZ header + deflate bytes, without a zlib footer/checksum.
        (path / (name + ".compressed.bin")).write_bytes(zlib.compress(packed)[:-4])
        pixels = np.full((height, width, 4), [17, 34, 68, 136], dtype="uint8")
        assert cv2.imwrite(str(path / (name + ".png")), pixels)
        source[key] = {"width": width, "height": height, "format": 1, "chain": [
            {"archive": archive, "image": image, "property": prop, "metadata": original},
            {"archive": target, "image": image, "property": prop,
             "metadata": canvas(width, height)}]}
    write_json(path / "raw.json", source)
    return source


def test_receipt_and_normalized_geometry_preserve_original_metadata(inputs, tmp_path):
    root, receipt, _ = inputs
    _, files, _ = exporter.copied_inputs(root, receipt)
    assert set(files) == exporter.REQUIRED
    output = tmp_path / "bundle"
    original = bundle(output)
    source, checks = exporter.validate_bundle(output)
    geometry = json.loads((output / "geometry.json").read_text())
    assert source == original
    assert len(geometry["footholds"]) == 205
    assert geometry["footholds"][0]["custom"] == 8
    assert geometry["footholds"][0]["piece"] == -1
    assert geometry["canvas_origin"] is None
    assert checks["minimap-canvas"]["pixels"] == 40710
    assert checks["player-marker"]["pixels"] == 144


@pytest.mark.parametrize("fault", ["hash", "missing", "traversal", "absolute", "duplicate",
                                  "copy", "size", "installed", "invalid-hash"])
def test_receipt_refuses_unsafe_or_changed_inputs(inputs, fault):
    root, receipt, rows = inputs
    if fault == "hash":
        rows[0]["sha256"] = "0" * 64
    elif fault == "missing":
        Path(rows[0]["copy"]).unlink()
    elif fault == "traversal":
        rows[0]["relative"] = "../escape.wz"
    elif fault == "absolute":
        rows[0]["relative"] = "C:/installed.wz"
    elif fault == "duplicate":
        rows.append(copy.deepcopy(rows[0]))
    elif fault == "copy":
        rows[0]["copy"] = str(root.parent / "elsewhere.wz")
    elif fault == "size":
        rows[0]["bytes"] = exporter.MAX_INPUT + 1
    elif fault == "installed":
        rows[0]["original"] = rows[0]["copy"]
    elif fault == "invalid-hash":
        rows[0]["sha256"] = "unverified"
    write_json(receipt, rows)
    with pytest.raises((ValueError, OSError)):
        exporter.copied_inputs(root, receipt)


@pytest.mark.parametrize("fault", ["identity", "counts", "modifier", "origin", "link-escape",
                                  "link-cycle", "link-target", "format", "pixels", "inflated"])
def test_bundle_refuses_loss_or_invalid_decoding(tmp_path, fault):
    output = tmp_path / "bundle"
    raw = bundle(output)
    if fault == "identity":
        raw["map_id"] = "000001000"
    elif fault == "counts":
        raw["raw"]["portal"].pop("0")
    elif fault == "modifier":
        raw["raw"]["foothold"]["1"]["0"]["0"].pop("piece")
    elif fault == "origin":
        raw["marker"]["properties"].pop("origin")
    elif fault == "link-escape":
        raw["minimap_canvas"]["chain"][1]["archive"] = "../outside.wz"
    elif fault == "link-cycle":
        raw["minimap_canvas"]["chain"].append(raw["minimap_canvas"]["chain"][0])
    elif fault == "link-target":
        raw["minimap_canvas"]["chain"][1]["image"] = "wrong.img"
    elif fault == "format":
        raw["player_marker"]["format"] = 2
    elif fault == "pixels":
        cv2.imwrite(str(output / "player-marker.png"), np.zeros((12, 12, 4), "uint8"))
    elif fault == "inflated":
        (output / "player-marker.compressed.bin").write_bytes(zlib.compress(b"x" * 100000))
    write_json(output / "raw.json", raw)
    with pytest.raises(ValueError):
        exporter.validate_bundle(output)


def test_partial_deflate_is_explicit_and_known_channels_are_checked(tmp_path):
    output = tmp_path / "bundle"
    raw = bundle(output)
    path = output / "player-marker.compressed.bin"
    packed = struct.pack("<6H", 0xFF00, 0xF0F0, 0xF00F, 0xFFFF, 0, 0x8421) * 24
    stream = zlib.compressobj()
    path.write_bytes(stream.compress(packed) + stream.flush(zlib.Z_SYNC_FLUSH))
    known = np.array([[0, 0, 255, 255], [0, 255, 0, 255], [255, 0, 0, 255],
                      [255, 255, 255, 255], [0, 0, 0, 0], [17, 34, 68, 136]], dtype="uint8")
    cv2.imwrite(str(output / "player-marker.png"), np.tile(known, (24, 1)).reshape(12, 12, 4))
    result = exporter.decode_canvas(output, "player-marker", raw["player_marker"])
    assert result["raw_deflate_stream_complete"] is False
    assert result["zlib_footer_checksum_verified"] is False


@pytest.mark.parametrize("target", ["existing", "copies", "src", "data", "installed"])
def test_output_protection(inputs, tmp_path, target):
    root, _, rows = inputs
    paths = {"existing": root, "copies": root / "new", "src": exporter.PROJECT / "src/new",
             "data": exporter.PROJECT / "data/new", "installed": Path(rows[0]["original"]).parent
             / "new"}
    with pytest.raises(ValueError):
        exporter.check_output(paths[target], root, [Path(row["original"]) for row in rows])


def parser_fixture(tmp_path):
    parser = tmp_path / "parser"
    parser.mkdir()
    for name in ("ClassicAssetExtractor.dll", "MapleLib.dll", "test.runtimeconfig.json"):
        (parser / name).write_bytes(b"fixture")
    pins = {p.name: exporter.digest(p) for p in parser.iterdir()}
    write_json(parser / "parser-receipt.json", {"schema": 1, "commit": exporter.PARSER_COMMIT,
                                              "extractor_sources": {
                                                  name: exporter.digest(exporter.PROJECT
                                                      / "tools/classic_asset_extractor" / name)
                                                  for name in ("Program.cs",
                                                               "ClassicAssetExtractor.csproj")},
                                              "files": pins})
    return parser / "ClassicAssetExtractor.dll"


@pytest.mark.parametrize("fault", ["binary", "commit", "extra"])
def test_parser_identity_is_pinned(tmp_path, fault):
    parser = parser_fixture(tmp_path)
    assert exporter.parser_files(parser)["commit"] == exporter.PARSER_COMMIT
    if fault == "binary":
        parser.write_bytes(b"changed")
    elif fault == "extra":
        (parser.parent / "extra.dll").write_bytes(b"injected")
    else:
        receipt = json.loads((parser.parent / "parser-receipt.json").read_text())
        receipt["commit"] = "different"
        write_json(parser.parent / "parser-receipt.json", receipt)
    with pytest.raises(ValueError):
        exporter.parser_files(parser)


def test_export_deterministic_and_failure_never_publishes(inputs, tmp_path, monkeypatch):
    root, receipt, _ = inputs
    parser = parser_fixture(tmp_path)

    def parse(command, **kwargs):
        assert kwargs["timeout"] == 30
        assert command[2] != str(root)
        bundle(Path(command[-1]))

    monkeypatch.setattr(exporter.subprocess, "run", parse)
    a, b = tmp_path / "a", tmp_path / "b"
    exporter.export(root, receipt, 60, a, parser)
    exporter.export(root, receipt, 60, b, parser)
    assert {p.name: p.read_bytes() for p in a.iterdir()} == {
        p.name: p.read_bytes() for p in b.iterdir()}
    manifest = json.loads((a / "manifest.json").read_text())
    assert manifest["input_sent"] is manifest["native_acceptance"] is False
    assert manifest["fixture_admission_ready"] is False

    def fail(command, **kwargs):
        Path(command[-1]).mkdir()
        (Path(command[-1]) / "partial").write_bytes(b"unfinished")
        raise subprocess.TimeoutExpired(command, 30)

    monkeypatch.setattr(exporter.subprocess, "run", fail)
    with pytest.raises(subprocess.TimeoutExpired):
        exporter.export(root, receipt, 60, tmp_path / "failed", parser)
    assert not (tmp_path / "failed").exists()
    assert not list(tmp_path.glob(".classic-export-*"))


def test_reparse_or_symlink_escape_is_rejected(tmp_path):
    target = tmp_path / "real"
    target.mkdir()
    link = tmp_path / "alias"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        # Junctions need no symbolic-link privilege on Windows.
        if __import__("os").name != "nt":
            pytest.skip("No symlink support")
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                       check=True, capture_output=True)
    with pytest.raises(ValueError, match="Reparse/symlink"):
        exporter.safe_path(link / "new")
