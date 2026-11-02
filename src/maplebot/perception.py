"""Replaceable perception using only operator-captured screenshot templates."""

import hashlib
import json
import math
import os
import time
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass, field, replace
from functools import cached_property
from itertools import combinations, pairwise
from pathlib import Path
from typing import Protocol

import cv2
import numpy as np

from .capture import Image
from .config import PerceptionConfig
from .enemy_tracking import EnemyTrack, EnemyTracker, partial_enemies
from .geometry import Rect
from .map_filter import MapFilter
from .reacquisition import RECOVERY_SECONDS, ConfirmedSprites


@dataclass(frozen=True)
class Detection:
    kind: str
    box: Rect
    confidence: float
    template: str = ""
    # Accepted below the confidence threshold because it is close to the last confirmed
    # position; see TemplateDetector._follow.
    tracked: bool = False
    # A recent full-name/sprite agreement; never supplied by positional tracking.
    identity: str | None = None
    track_id: str | None = None
    visible_bounds: Rect | None = None


@dataclass(frozen=True)
class Observation:
    player: Detection | None
    monsters: list[Detection]
    failures: list[str] = field(default_factory=list)
    camera_shift: tuple[float, float] = (0, 0)
    camera_confidence: float = 0
    enemy_tracks: list[EnemyTrack] = field(default_factory=list)
    # Display/diagnostic snapshot of the player track; decisions never read it.
    player_tracking: dict | None = None


def masked_score(observed: np.ndarray, observed_gray: np.ndarray, reference: np.ndarray,
                 reference_gray: np.ndarray) -> float:
    """Sprite similarity over matching pixel lists: 0.6 color agreement + 0.4 structure."""
    centered = reference_gray - reference_gray.mean()
    energy = float((reference * reference).sum())
    color = 1 - float(((observed - reference) ** 2).sum()) / max(
        1e-6, np.sqrt(energy * float((observed * observed).sum()))
    )
    centered_observed = observed_gray - observed_gray.mean()
    structure = float(centered @ centered_observed) / max(
        1e-6, float(np.linalg.norm(centered) * np.linalg.norm(centered_observed))
    )
    return float(np.clip(0.6 * color + 0.4 * structure, 0, 1))


class Detector(Protocol):
    def detect(self, image: Image, now: float | None = None, *,
               monsters: bool = True) -> Observation: ...


@dataclass(frozen=True)
class SpriteSignature:
    offsets: np.ndarray
    colors: np.ndarray
    buckets: tuple[np.ndarray, ...]

    @cached_property
    def bucket_owners(self) -> tuple[np.ndarray, np.ndarray]:
        """Every bucket's color bins in one array, and the sample each bin belongs to."""
        return np.concatenate(self.buckets), np.repeat(
            np.arange(len(self.buckets)), [len(bins) for bins in self.buckets])

    @cached_property
    def color_ranges(self) -> tuple[np.ndarray, np.ndarray]:
        """Per sample and BGR channel (plus an ignored fourth byte): the lowest value within
        12 of the sample, and the span of accepted values above it."""
        low = np.zeros((len(self.colors), 4), dtype=np.uint8)
        span = np.full((len(self.colors), 4), 255, dtype=np.uint8)
        low[:, :3] = np.maximum(self.colors - 12, 0)
        span[:, :3] = np.minimum(self.colors + 12, 255) - low[:, :3]
        return low, span


@dataclass(frozen=True)
class Template:
    kind: str
    name: str
    image: Image
    gray: Image
    anchor: Rect | None = None
    mask: Image | None = None
    signature: SpriteSignature | None = None

    @cached_property
    def anchored(self) -> tuple[Image, Image, Image]:
        """The anchor crop in color and gray, and its half-resolution gray proposal."""
        anchor = self.anchor
        assert anchor is not None
        rows = slice(anchor.y, anchor.y + anchor.height)
        cols = slice(anchor.x, anchor.x + anchor.width)
        gray = self.gray[rows, cols]
        return self.image[rows, cols], gray, cv2.pyrDown(gray)


@dataclass(frozen=True)
class SpriteLayout:
    """One sprite batch's samples, concatenated in template order, for one frame width."""

    counts: np.ndarray  # samples per template
    bases: np.ndarray  # each template's first sample, then the total
    sample_item: np.ndarray  # template of each sample
    bins: np.ndarray  # every sample's 4-bit color bins
    bin_sample: np.ndarray  # sample of each bin
    offsets: np.ndarray  # (y, x) of each sample in its sprite
    samples: np.ndarray  # pixel offset of each sample, then a padding sample
    low: np.ndarray  # accepted color range of each sample, then the padding range
    span: np.ndarray
    max_misses: np.ndarray
    heights: np.ndarray
    widths: np.ndarray

    @classmethod
    def build(cls, templates: list[Template], cols: int) -> "SpriteLayout":
        signatures = [template.signature for template in templates]
        assert all(signature is not None for signature in signatures)
        counts = np.array([len(signature.colors) for signature in signatures])
        bases = np.concatenate(([0], np.cumsum(counts)))
        offsets = np.concatenate([signature.offsets for signature in signatures])
        return cls(
            counts=counts,
            bases=bases,
            sample_item=np.repeat(np.arange(len(templates)), counts),
            bins=np.concatenate([signature.bucket_owners[0] for signature in signatures]),
            bin_sample=np.concatenate([signature.bucket_owners[1] + base for signature, base
                                       in zip(signatures, bases, strict=False)]),
            offsets=offsets,
            samples=np.concatenate((offsets[:, 0] * cols + offsets[:, 1],
                                    np.zeros(1, np.int64))),
            low=np.concatenate([signature.color_ranges[0] for signature in signatures]
                               + [np.zeros((1, 4), np.uint8)]),
            span=np.concatenate([signature.color_ranges[1] for signature in signatures]
                                + [np.full((1, 4), 255, np.uint8)]),
            max_misses=(counts + 4) // 5,
            heights=np.array([template.image.shape[0] for template in templates]),
            widths=np.array([template.image.shape[1] for template in templates]),
        )


@dataclass(frozen=True)
class NameTag:
    """The character's name label: white text on a translucent dark box under the feet."""

    name: str
    # Binary glyph pixels, cropped to the text plus 1 px so it stays inside the dark box.
    text: Image
    text_top: int
    player_size: tuple[int, int] = (44, 64)
    decoys: tuple[tuple[int, int], ...] = ()
    frame: tuple[int, int] | None = None


# Text pixels are near-white. The translucent box behind them stays below this even
# over white clouds (~180), so glyph shapes compare cleanly on any background.
NAMETAG_TEXT = 245
# Gap between the player's feet and the top of the name text, in native pixels.
NAMETAG_FEET_GAP = 2
# Only a clean, unobstructed tag may refresh the in-memory player sprite.
REFRESH_TAG_CONFIDENCE = 0.97
REFRESH_SECONDS = 3.0
# Upper bound of the 0.6-weighted color term, with slack for floating-point rounding.
COLOR_WEIGHT_CAP = 0.6 * 1.001
# Color samples checked in the first and each later step of the catalog sprite search.
# Any grouping gives the same result; these measured fastest on Middle Forest composites.
FIRST_SAMPLES, SAMPLE_BLOCK = 8, 6
# Catalog sprite templates matched together in one task.
SPRITE_BATCH = 32
# Half-resolution proposal score below which sprite search stops. Across 1698 recorded
# frames every accepted sprite proposed at 0.57 or more; lower proposals were background.
COARSE_FLOOR = 0.45
# Search radius around the last confirmed position: base plus walking speed, capped.
TRACK_RADIUS, TRACK_SPEED, TRACK_MAX_RADIUS = 12, 240, 80
# The last box moves by the camera shift only when the shift is this certain, and by at most
# this much of the player's own per-frame world motion; otherwise it stays where it was.
PREDICTION_RESPONSE = 0.35
PREDICTION_MAX_STEP = 40
FULL_SCAN_EVERY = 4
# Monsters outside the player's search window are searched one grid cell per frame, so
# every frame costs about the same instead of a whole-frame scan once a second.
TILE_COLUMNS, TILE_ROWS = 4, 2
LOOKALIKE_SEPARATION = 30


def nametag_parts(image: Image) -> tuple[Image, int, tuple[int, int]]:
    """Returns the glyph mask, the text top within it, and the mask's origin in `image`."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    text = gray >= NAMETAG_TEXT
    if np.count_nonzero(text) < 20:
        raise ValueError("Select the whole name tag, including all of its white text")
    outside = gray[cv2.dilate(np.uint8(text), np.ones((3, 3), np.uint8)) == 0]
    if not outside.size or float(outside.mean()) > 120:
        raise ValueError("Name tag needs its dark background box; select it tightly")
    ys, xs = np.nonzero(text)
    top, left = max(0, int(ys.min()) - 1), max(0, int(xs.min()) - 1)
    bottom, right = min(gray.shape[0], int(ys.max()) + 2), min(gray.shape[1], int(xs.max()) + 2)
    return np.float32(text[top:bottom, left:right]), int(ys.min()) - top, (left, top)


def text_overlap(gray: Image, text: Image, near_white: Image | None = None) -> Image:
    """F1 overlap between the glyph mask and near-white pixels at every position.

    The frame is padded left and right so a tag running off the edge still scores; its
    hidden glyphs count as missing. Index x maps to tag x - (width - 1). `near_white` is
    float32(gray >= NAMETAG_TEXT) when the caller already computed it.
    """
    height, width = text.shape
    if near_white is None:
        near_white = np.float32(gray >= NAMETAG_TEXT)
    observed = cv2.copyMakeBorder(
        near_white, 0, 0, width - 1, width - 1, cv2.BORDER_CONSTANT, value=0
    )
    shared = cv2.matchTemplate(observed, text, cv2.TM_CCORR)
    counts = cv2.boxFilter(
        observed,
        -1,
        (width, height),
        normalize=False,
        anchor=(0, 0),
        borderType=cv2.BORDER_CONSTANT,
    )[: shared.shape[0], : shared.shape[1]]
    return 2 * shared / (float(text.sum()) + counts)


class CameraTracker:
    def __init__(self) -> None:
        self.previous: np.ndarray | None = None
        self.window: np.ndarray | None = None
        self.previous_gray: np.ndarray | None = None
        # This frame's feature points, found in the background for the next update: they
        # depend only on the frame, so the next translation is unchanged, just earlier.
        self.points: tuple[np.ndarray, Future] | None = None
        self.features: ThreadPoolExecutor | None = None

    def update(self, image: Image) -> tuple[tuple[float, float], float]:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        previous_gray, self.previous_gray = self.previous_gray, gray
        from .camera_motion import feature_points, feature_translation

        pending = self.points if self.points and self.points[0] is previous_gray else None
        if self.features is None:
            self.features = ThreadPoolExecutor(max_workers=1, thread_name_prefix="camera")
        self.points = (gray, self.features.submit(feature_points, gray))
        small = cv2.resize(gray, None, fx=0.5, fy=0.5).astype(np.float32)
        previous, self.previous = self.previous, small
        if previous is None or previous.shape != small.shape or float(small.std()) < 2:
            return (0, 0), 0
        if self.window is None or self.window.shape != small.shape:
            self.window = cv2.createHanningWindow((small.shape[1], small.shape[0]), cv2.CV_32F)
        # OpenCV applies the window in place; keep next frame's reference unwindowed.
        (dx, dy), response = cv2.phaseCorrelate(previous.copy(), small.copy(), self.window)
        # Strong global correlation can still drift with animation/overlays. Prefer
        # distributed forward/backward-verified scene features when available.
        hint = (dx * 2, dy * 2) if np.isfinite([dx, dy]).all() else None
        points = pending[1].result() if pending else None
        verified, confidence = feature_translation(previous_gray, gray, hint, points)
        if confidence >= .60:
            return verified, confidence
        if not np.isfinite([dx, dy, response]).all() or response < 0.35:
            return (0, 0), 0
        if abs(dx * 2) > image.shape[1] * 0.2 or abs(dy * 2) > image.shape[0] * 0.2:
            return (0, 0), 0
        return (dx * 2, dy * 2), float(response)


class TemplateDetector:
    def __init__(self, directory: Path, config: PerceptionConfig) -> None:
        self.directory, self.config = directory, config
        self.enemy_source = None
        self.enemy_scan_context = None
        self.enemy_empty_observations = 0
        self.enemy_scan_frame = None
        self.enemy_tile = -1  # grid cell searched last; -1 before the first
        self.enemy_cell: Rect | None = None  # the cell searched this frame, frame pixels
        self.enemy_scan_stage = "local"
        self.templates: list[Template] = []
        self.nametags: list[NameTag] = []
        # Sprites snapshotted from frames where the tag confirmed the player; memory only.
        self.fresh: deque[list[Template]] = deque(maxlen=2)
        self.refreshed = float("-inf")
        # Last position, when it was last confirmed, and when evidence last supported it.
        self.track: tuple[Rect, float, float] | None = None
        # The player's world motion per frame (screen motion minus camera shift), and the
        # box and shift this frame's prediction started from. Prediction only centres the
        # search; it never confirms identity or makes a frame fresh.
        self.world_step = (0.0, 0.0)
        self.predicted: tuple[Rect, tuple[float, float]] | None = None
        # Name of the tag that last confirmed the player. Following accepts partial evidence
        # only from this tag, never from another player's.
        self.track_tag: str | None = None
        # Previous confident monster boxes (full frame) and the current search origin.
        # Together with the player track they mark pixels that may cover a sprite.
        self.previous_monsters: tuple[Rect, ...] = ()
        self.origin = (0, 0)
        # Columns (x0, x1) that replace the whole-frame fallback while the minimap marker
        # pins the player to one screen edge; thresholds are unchanged.
        self.strip: tuple[int, int] | None = None
        self.occluders: tuple[Rect, ...] = ()
        # During a window pass, the part of it player templates search (x, y, w, h).
        self.player_area: tuple[int, int, int, int] | None = None
        self.zones = np.zeros((1, 1), dtype=np.uint8)
        self.zone_sums = cv2.integral(self.zones)
        self.camera = CameraTracker()
        # Set by the runtime when the taught area's minimap confirms the current map.
        self.taught_map = False
        # Active templates for the last (templates, allowed species, monsters) selection.
        self.active: tuple[list[Template], tuple, list[Template]] | None = None
        self.masked_cache: dict = {}
        self.pool = ThreadPoolExecutor(
            max_workers=min(8, os.cpu_count() or 1), thread_name_prefix="match"
        )
        self.reload()

    def reload(self) -> None:
        self.enemy_scan_context = None
        self.masked_cache.clear()
        self.enemy_tracker = EnemyTracker(self.config)
        self.enemy_context = None
        self.enemy_geometry_ready = False
        self.enemy_geometry_retry_at = float("-inf")
        geometry_path = self.directory / "enemy-occlusion.json"
        self.enemy_geometry = (json.loads(geometry_path.read_text("utf-8"))
                               if geometry_path.exists() else {})
        self.confirmed_sprites = ConfirmedSprites()
        if hasattr(self, "map_filter"):
            self.map_filter.close()
        templates = []
        manifest_path = self.directory / "catalog" / "manifest.json"
        manifest = json.loads(manifest_path.read_text("utf-8")) if manifest_path.exists() else {}
        entries = {Path(entry["file"]).name: entry for entry in manifest.get("entries", [])}
        catalog_names, catalog_frames = set(), 0
        seen_catalog = set()
        for kind, folder in (
            ("player", "player"),
            ("monster", "monster"),
            ("monster", "catalog/monster"),
        ):
            for path in sorted((self.directory / folder).glob("*.png")):
                if folder == "catalog/monster" and path.name not in entries:
                    continue
                raw = self._read_template(path)
                name = path.stem
                if folder == "catalog/monster":
                    entry = entries.get(path.name)
                    if entry is None:
                        continue
                    digest = hashlib.sha256(path.read_bytes()).hexdigest()
                    if digest != entry["sha256"]:
                        raise ValueError(f"Catalog image hash mismatch: {path.name}")
                    catalog_names.add(entry["name"])
                    catalog_frames += 1
                    identity = (digest, entry["name"])
                    if identity in seen_catalog:
                        continue
                    seen_catalog.add(identity)
                    name = f"catalog:{entry['name']}:{entry['animation']}-{entry['frame']}"
                templates.extend(self._variants(kind, name, raw, path))
        self.templates = templates
        self.layouts: dict[tuple, SpriteLayout] = {}
        self.map_filter = MapFilter(self.directory, list(entries.values()),
                                    self.config.spawn_source, self.config.spawn_revision)
        self.nametags = [
            self.load_nametag(path) for path in sorted((self.directory / "nametag").glob("*.png"))
        ]
        self.fresh.clear()
        self.track, self.misses, self.search_window = None, 0, None
        self.lookalike_at = float("-inf")
        # Whole-frame player searches since the track was lost, and the last name/sprite
        # conflict; together they decide when poses may search only under the name tag.
        self.full_scans, self.conflict_at = 0, float("-inf")
        # A player found from the name tag alone gets one whole-frame check next frame,
        # so a look-alike or a sprite away from the tag still vetoes it one frame later.
        self.verify_scan = self.verifying = False
        self.world_step, self.predicted, self.track_tag = (0.0, 0.0), None, None
        self.previous_monsters = ()
        self.camera = CameraTracker()
        self.catalog_info = {
            "nametags": len(self.nametags),
            "species": len(catalog_names),
            "frames": catalog_frames,
            "names": sorted(catalog_names),
            "network_during_detection": False,
            "spawn_source": self.map_filter.source,
            "spawn_revision": self.map_filter.revision,
            "spawn_error": self.map_filter.source_error,
            "spawn_maps": len(self.map_filter.profiles),
        }


    def add(self, path: Path, kind: str) -> None:
        """Load one newly taught file without re-reading the sprite catalog."""
        if kind == "nametag":
            self.nametags.append(self.load_nametag(path))
            self.catalog_info = {**self.catalog_info, "nametags": len(self.nametags)}
        else:
            raw = self._read_template(path)
            self.templates = [*self.templates, *self._variants(kind, path.stem, raw, path)]
        self.fresh.clear()

    def _read_template(self, path: Path) -> Image:
        raw = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        if raw is None or raw.ndim != 3 or raw.shape[2] not in (3, 4):
            raise ValueError(f"Unreadable template: {path}")
        self.validate(raw[:, :, :3].copy())
        return raw

    def _variants(self, kind: str, name: str, raw: Image, path: Path) -> list[Template]:
        image = raw[:, :, :3].copy()
        variants: list[Template] = []
        if raw.shape[2] == 4:
            full_mask = np.uint8(raw[:, :, 3] >= 250) * 255
            if np.count_nonzero(full_mask) < 16:
                raise ValueError(f"Reference has no usable opaque foreground: {path.name}")
            x, y, width, height = cv2.boundingRect(full_mask)
            anchor = Rect(x, y, width, height)
            mask = full_mask[y : y + height, x : x + width].copy()
        else:
            anchor, mask = self._player_anchor(image) if kind == "player" else (None, None)
        for mirrored in (False, True):
            variant = cv2.flip(image, 1) if mirrored else image
            variant_anchor, variant_mask = anchor, mask
            if mirrored and anchor is not None:
                variant_anchor = Rect(
                    image.shape[1] - anchor.x - anchor.width,
                    anchor.y,
                    anchor.width,
                    anchor.height,
                )
                variant_mask = cv2.flip(mask, 1)
            variant_gray = cv2.cvtColor(variant, cv2.COLOR_BGR2GRAY)
            signature = None
            if raw.shape[2] == 4 and variant_anchor is not None:
                box = variant_anchor
                signature = self._sprite_signature(
                    variant[box.y : box.y + box.height, box.x : box.x + box.width],
                    variant_mask,
                    box,
                )
            variants.append(
                Template(
                    kind,
                    name,
                    variant,
                    variant_gray,
                    variant_anchor,
                    variant_mask,
                    signature,
                )
            )
        return variants

    @staticmethod
    def load_nametag(path: Path) -> NameTag:
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError(f"Unreadable name tag: {path}")
        text, text_top, _ = nametag_parts(image)
        meta_path = path.with_suffix(".json")
        meta = json.loads(meta_path.read_text("utf-8")) if meta_path.exists() else {}
        return NameTag(
            path.stem,
            text,
            text_top,
            tuple(meta.get("player_size", (44, 64))),
            tuple(tuple(item) for item in meta.get("decoys", [])),
            tuple(meta["frame"]) if meta.get("frame") else None,
        )

    def nametag_matches(self, gray: Image, tag: NameTag, floor: float,
                        near_white: Image | None = None) -> list[Detection]:
        """Glyph-shape matches. Text on a light background (chat rows, clouds outside
        the box) adds near-white pixels around the glyphs and lowers the score."""
        height, width = tag.text.shape
        if height > gray.shape[0] or width > gray.shape[1]:
            return []
        score = text_overlap(gray, tag.text, near_white)
        decoys = tag.decoys if tag.frame == (gray.shape[1], gray.shape[0]) else ()
        found = []
        for _ in range(self.config.max_candidates):
            _, peak, _, (x, y) = cv2.minMaxLoc(score)
            if peak < floor:
                break
            score[max(0, y - height) : y + height, max(0, x - width) : x + width] = 0
            x -= width - 1
            if any(abs(x - a) <= 4 and abs(y - b) <= 4 for a, b in decoys):
                continue  # Static copy of the name, e.g. the HUD status bar.
            found.append(
                Detection("nametag", Rect(x, y, width, height), round(float(peak), 6), tag.name)
            )
        return found

    @staticmethod
    def body_from_nametag(tag: NameTag, box: Rect) -> Rect:
        width, height = tag.player_size
        feet = box.y + tag.text_top - NAMETAG_FEET_GAP
        return Rect(round(box.x + box.width / 2 - width / 2), feet - height, width, height)

    @staticmethod
    def validate(image: Image) -> None:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        if min(gray.shape) < 6 or gray.std() < 5 or np.count_nonzero(cv2.Canny(gray, 50, 150)) < 8:
            raise ValueError("Select a textured sprite at least 6×6 pixels, not a flat background")

    @staticmethod
    def _player_anchor(image: Image) -> tuple[Rect | None, Image | None]:
        """Derive a stable foreground component; keep user examples unchanged on disk."""
        height, width = image.shape[:2]
        if min(height, width) < 24:
            return None, None
        labels = np.zeros((height, width), dtype=np.uint8)
        margin = max(1, width // 12)
        labels[2 : int(height * 0.8), margin : width - margin] = cv2.GC_PR_FGD
        # The centered character's upper body is foreground; labels/feet animate below it.
        for fraction in (0.25, 0.4):
            x, y = width // 2, round(height * fraction)
            labels[y - 2 : y + 3, x - 2 : x + 3] = cv2.GC_FGD
        cv2.setRNGSeed(0)
        try:
            cv2.grabCut(
                image,
                labels,
                None,
                np.zeros((1, 65), np.float64),
                np.zeros((1, 65), np.float64),
                5,
                cv2.GC_INIT_WITH_MASK,
            )
        except cv2.error:
            return None, None
        mask = np.uint8((labels == cv2.GC_FGD) | (labels == cv2.GC_PR_FGD)) * 255
        count, components, stats, _ = cv2.connectedComponentsWithStats(mask)
        if count < 2:
            return None, None
        component = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        mask = np.uint8(components == component) * 255
        pixels = np.count_nonzero(mask)
        if pixels < 64 or not 0.05 <= pixels / mask.size <= 0.7:
            return None, None
        x, y, w, h = cv2.boundingRect(mask)
        if min(w, h) < 12:
            return None, None
        return Rect(x, y, w, h), mask[y : y + h, x : x + w].copy()

    @staticmethod
    def _sprite_signature(image: Image, mask: Image, anchor: Rect) -> SpriteSignature:
        positions = np.column_stack(np.nonzero(mask))
        colors = image[mask != 0].astype(np.int16)
        quantized = colors >> 4
        codes = (quantized[:, 0] << 8) | (quantized[:, 1] << 4) | quantized[:, 2]
        unique, counts = np.unique(codes, return_counts=True)
        selected = []
        for code in unique[np.argsort(counts)[::-1][:24]]:
            indices = np.flatnonzero(codes == code)
            selected.append(int(indices[len(indices) // 2]))
        offsets = positions[selected] + (anchor.y, anchor.x)
        values = colors[selected]
        buckets = []
        for color in values:
            low, high = np.maximum(color - 12, 0) >> 4, np.minimum(color + 12, 255) >> 4
            grid = np.meshgrid(
                *(np.arange(a, b + 1) for a, b in zip(low, high, strict=True)), indexing="ij"
            )
            buckets.append(((grid[0] << 8) | (grid[1] << 4) | grid[2]).ravel())
        return SpriteSignature(offsets, values, tuple(buckets))

    @staticmethod
    def _color_index(image: Image) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Pixels sorted by 4-bit color code, the code boundaries, and every pixel's BGR
        bytes packed into one uint32, in row order."""
        colors = image.astype(np.uint16) >> 4
        codes = ((colors[:, :, 0] << 8) | (colors[:, :, 1] << 4) | colors[:, :, 2]).ravel()
        order = np.argsort(codes, kind="stable")
        boundaries = np.concatenate(([0], np.cumsum(np.bincount(codes, minlength=4096))))
        packed = np.zeros((image.shape[0] * image.shape[1], 4), dtype=np.uint8)
        packed[:, :3] = image.reshape(-1, 3)
        return order, boundaries, packed.view(np.uint32).reshape(-1)

    def _sprite_candidates(
        self,
        image: Image,
        gray: Image,
        template: Template,
        floor: float,
        index: tuple[np.ndarray, np.ndarray, np.ndarray],
    ) -> list[Detection]:
        return self._sprite_batch(image, gray, [template], floor, index)[0]

    def _sprite_layout(self, templates: list[Template], cols: int) -> SpriteLayout:
        """The frame-independent arrays of one sprite batch, built once per batch."""
        key = (cols, *map(id, templates))
        layout = self.layouts.get(key)
        if layout is None:
            if len(self.layouts) >= 256:
                self.layouts.clear()  # The active species changed many times.
            layout = self.layouts[key] = SpriteLayout.build(templates, cols)
        return layout

    def _sprite_batch(
        self,
        image: Image,
        gray: Image,
        templates: list[Template],
        floor: float,
        index: tuple[np.ndarray, np.ndarray, np.ndarray],
    ) -> list[list[Detection]]:
        """Catalog sprite matches for each template, in template order.

        Each template gets the result of searching it alone. Matching many at once replaces
        thousands of small array operations per frame with a few large ones.
        """
        order, boundaries, packed = index
        rows, cols = image.shape[:2]
        layout = self._sprite_layout(templates, cols)
        occluders = self.occluders
        sums = self.zone_sums
        counts, bases, sample_item = layout.counts, layout.bases, layout.sample_item
        # Rank each template's samples by how common their colors are in this frame. Tied
        # samples may rank either way: any max_misses + 1 seeds propose every position that
        # can pass, and checking samples in another order drops the same positions.
        sizes = np.bincount(layout.bin_sample, weights=boundaries[layout.bins + 1]
                            - boundaries[layout.bins], minlength=bases[-1]).astype(np.int64)
        ranked = np.lexsort((sizes, sample_item))
        rank = np.empty_like(ranked)
        rank[ranked] = np.arange(len(ranked)) - bases[sample_item[ranked]]
        # These sparse, color-selected samples are not an area/confidence estimate.
        # A few covered samples can still leave a strong full-mask match below.
        max_misses = layout.max_misses
        # Sprites next to the player or a previous monster may be partly covered. There,
        # more samples may miss, and verification uses only the uncovered pixels.
        relaxed = np.maximum(max_misses, counts // 2) if occluders else max_misses
        heights, widths = layout.heights, layout.widths

        # Multiple seeds keep a covered proposal pixel from hiding an otherwise valid sprite.
        # Three extra seeds are enough to find the visible part of a covered sprite.
        seeds = np.minimum(max_misses + (4 if occluders else 1), counts)
        seeded = (rank < seeds[sample_item])[layout.bin_sample]
        seed_bins, seed_sample = layout.bins[seeded], layout.bin_sample[seeded]
        starts = boundaries[seed_bins]
        lengths = boundaries[seed_bins + 1] - starts
        found: list[list[Detection]] = [[] for _ in templates]
        if not lengths.sum():
            return found
        # Every pixel of every seed's color bins, and the seed sample that found it.
        owner = np.repeat(np.arange(len(seed_bins)), lengths)
        pixels = order[starts[owner] + np.arange(len(owner))
                       - np.repeat(np.cumsum(lengths) - lengths, lengths)]
        seed = seed_sample[owner]
        item = sample_item[seed]
        ys = pixels // cols - layout.offsets[seed, 0]
        xs = pixels % cols - layout.offsets[seed, 1]
        valid = (ys >= 0) & (xs >= 0) & (ys + heights[item] <= rows) & (xs + widths[item] <= cols)
        extra = valid & (rank[seed] > max_misses[item])
        if extra.any():
            # Extra seeds only matter where something may cover the sprite.
            ey, ex, covering = ys[extra], xs[extra], item[extra]
            bottom = np.minimum(ey + heights[covering], sums.shape[0] - 1)
            right = np.minimum(ex + widths[covering], sums.shape[1] - 1)
            valid[extra] = (sums[bottom, right] - sums[ey, right] - sums[bottom, ex]
                            + sums[ey, ex]) > 0
        # A position several seeds propose is checked several times; the checks are per
        # position, so survivors are deduplicated at the end instead of sorting them all.
        positions, item = (ys * cols + xs)[valid], item[valid]

        # Indexed color patterns propose exact native-pixel positions; full masks verify them.
        # Miss counts only grow, so checking samples in blocks, in any order, drops the same
        # positions as checking them one at a time, with far fewer array operations. Every
        # position matches a seed that proposed it, so the rarest non-seed samples go first
        # and rule out background positions; the seeds come last. The last sample never
        # misses and pads shorter signatures.
        owners = sample_item[ranked]
        order_rank, seeded_count = rank[ranked], seeds[owners]
        column = np.where(order_rank >= seeded_count, order_rank - seeded_count,
                          counts[owners] - seeded_count + order_rank)
        checks = np.full((len(templates), counts.max()), len(layout.samples) - 1)
        checks[owners, column] = ranked
        # Per template and check: the sample's pixel offset and accepted color range.
        offsets, low, span = layout.samples[checks], layout.low[checks], layout.span[checks]
        zones = self.zones.reshape(-1)
        misses = np.zeros(len(positions), dtype=np.int16)
        unexplained = np.zeros(len(positions), dtype=np.int16)
        bounds = [0, *range(FIRST_SAMPLES, checks.shape[1], SAMPLE_BLOCK), checks.shape[1]]
        for start, stop in pairwise(bounds):
            if not len(positions):
                return found
            at = positions[:, None] + offsets[item, start:stop]
            # A channel more than 12 from the sample wraps past the span when offset by low.
            observed = packed[at].view(np.uint8).reshape(*at.shape, 4)
            observed -= low[item, start:stop]
            # Any channel out of range leaves a nonzero byte in that sample's 4-byte word.
            wrong = (observed > span[item, start:stop]).view(np.uint32)[:, :, 0] != 0
            misses += wrong.sum(axis=1, dtype=np.int16)
            if occluders:
                # A differing sample inside a covering zone is explained, not a miss.
                wrong &= zones[at] == 0
            unexplained += wrong.sum(axis=1, dtype=np.int16)
            valid = (unexplained <= max_misses[item]) & (misses <= relaxed[item])
            positions, item = positions[valid], item[valid]
            misses, unexplained = misses[valid], unexplained[valid]
        for row in np.unique(item):
            survivors = np.unique(positions[item == row])
            found[row] = self._sprite_scores(
                image, gray, templates[row], floor, survivors // cols, survivors % cols)
        return found

    def _sprite_scores(self, image: Image, gray: Image, template: Template, floor: float,
                       ys: np.ndarray, xs: np.ndarray) -> list[Detection]:
        """Full-mask confidence at the given sprite positions, best first."""
        anchor = template.anchor
        assert anchor is not None and template.mask is not None
        mask = template.mask != 0
        reference = template.image[
            anchor.y : anchor.y + anchor.height, anchor.x : anchor.x + anchor.width
        ][mask].astype(np.float32)
        reference_gray = template.gray[
            anchor.y : anchor.y + anchor.height, anchor.x : anchor.x + anchor.width
        ][mask].astype(np.float32)
        # Score every proposed position at once; same formula as masked_score().
        rows, cols = np.nonzero(mask)
        rows, cols = rows + anchor.y, cols + anchor.x
        centered = reference_gray - reference_gray.mean()
        reference_norm = float(np.linalg.norm(centered))
        energy = float((reference * reference).sum())
        confidences = np.empty(len(xs), dtype=np.float32)
        for start in range(0, len(xs), 256):
            py = ys[start:start + 256, None] + rows
            px = xs[start:start + 256, None] + cols
            observed = image[py, px].astype(np.float32)
            observed_gray = gray[py, px].astype(np.float32)
            color = 1 - ((observed - reference) ** 2).sum(axis=(1, 2)) / np.maximum(
                1e-6, np.sqrt(energy * (observed * observed).sum(axis=(1, 2))))
            centered_observed = observed_gray - observed_gray.mean(axis=1, keepdims=True)
            structure = (centered_observed @ centered) / np.maximum(
                1e-6, reference_norm * np.linalg.norm(centered_observed, axis=1))
            confidences[start:start + 256] = np.clip(0.6 * color + 0.4 * structure, 0, 1)
        found = []
        for x, y, confidence in zip(xs, ys, confidences.tolist(), strict=True):
            if confidence >= floor:
                found.append(
                    Detection(
                        template.kind,
                        Rect(int(x), int(y), template.image.shape[1], template.image.shape[0]),
                        round(confidence, 6),
                        template.name,
                    )
                )
        return sorted(found, key=lambda item: item.confidence, reverse=True)[
            : self.config.max_candidates
        ]

    def _anchor_candidates(
        self,
        image: Image,
        gray: Image,
        template: Template,
        floor: float,
        coarse: Image | None = None,
    ) -> list[Detection]:
        anchor = template.anchor
        assert anchor is not None and template.mask is not None
        reference, reference_gray, reference_coarse = template.anchored
        # Reuse only byte-identical native crops from this template's previous search.
        # Each template owns its entries while searches run in parallel.
        previous = self.masked_cache.get(id(template), ({}, template))[0]
        current = {}
        self.masked_cache[id(template)] = (current, template)

        def match(crop, reference, method, bounds):
            key = (method, bounds)
            saved = previous.get(key)
            if saved is not None and np.array_equal(crop, saved[0]):
                result = saved[1]
            else:
                result = cv2.matchTemplate(crop, reference, method, mask=template.mask)
            current[key] = (crop.copy(), result.copy())
            return result.copy()
        # Half-resolution grayscale proposals, then masked verification in native crops.
        coarse = cv2.pyrDown(gray) if coarse is None else coarse
        if (reference_coarse.shape[0] > coarse.shape[0]
                or reference_coarse.shape[1] > coarse.shape[1]):
            return []
        proposals = cv2.matchTemplate(coarse, reference_coarse, cv2.TM_CCOEFF_NORMED)
        proposals = np.nan_to_num(proposals, copy=False, nan=-1, posinf=-1, neginf=-1)
        found = []
        bounds = Rect(0, 0, image.shape[1], image.shape[0])
        full_height, full_width = template.image.shape[:2]
        for _ in range(self.config.max_candidates):
            _, peak, _, (cx, cy) = cv2.minMaxLoc(proposals)
            if peak < COARSE_FLOOR:
                break
            x, y = cx * 2, cy * 2
            left, top = max(0, x - 4), max(0, y - 4)
            right = min(image.shape[1], x + anchor.width + 4)
            bottom = min(image.shape[0], y + anchor.height + 4)
            # A box from this crop is only kept inside the frame; skip crops where none fits.
            fits = (max(0, left - anchor.x)
                    <= min(right - anchor.width, image.shape[1] - full_width + anchor.x) - anchor.x
                    and max(0, top - anchor.y)
                    <= min(bottom - anchor.height, image.shape[0] - full_height + anchor.y)
                    - anchor.y)
            structure = None
            if fits:
                structure = match(
                    gray[top:bottom, left:right],
                    reference_gray,
                    cv2.TM_CCOEFF_NORMED,
                    (left, top, right, bottom),
                )
                # NaN (a flat crop) would score 0; -1 keeps it below every floor.
                cv2.patchNaNs(structure, -1)
            # Color agreement is at most 1, so weak structure alone rules the crop out.
            if (structure is not None
                    and COLOR_WEIGHT_CAP + 0.4 * cv2.minMaxLoc(structure)[1] >= floor):
                color = 1 - match(
                    image[top:bottom, left:right], reference, cv2.TM_SQDIFF_NORMED,
                    (left, top, right, bottom),
                )
                score = 0.6 * color + 0.4 * structure
                if not cv2.checkRange(score)[0]:
                    score = np.nan_to_num(score, copy=False, nan=0, posinf=0, neginf=0)
                _, confidence, _, (dx, dy) = cv2.minMaxLoc(score)
                box = Rect(
                    left + dx - anchor.x,
                    top + dy - anchor.y,
                    template.image.shape[1],
                    template.image.shape[0],
                )
                if confidence >= floor and bounds.contains(box):
                    found.append(
                        Detection(template.kind, box, round(float(confidence), 6), template.name)
                    )
            proposals[
                max(0, cy - anchor.height // 4) : cy + anchor.height // 4 + 1,
                max(0, cx - anchor.width // 4) : cx + anchor.width // 4 + 1,
            ] = -1
        return found

    def _candidates(
        self, image: Image, gray: Image, templates: list[Template], floor: float
    ) -> list[Detection]:
        usable = [
            template for template in templates
            if template.gray.shape[0] <= image.shape[0] and template.gray.shape[1] <= image.shape[1]
        ]
        active_ids = {id(template) for template in usable}
        self.masked_cache = {key: value for key, value in self.masked_cache.items()
                             if key in active_ids}
        color_index = (
            self._color_index(image)
            if any(template.signature is not None for template in usable) else None
        )

        coarse = cv2.pyrDown(gray) if any(t.anchor is not None for t in usable) else None

        area = self.player_area

        def search(template: Template) -> list[Detection]:
            if area is None or template.kind != "player":
                return self._template_candidates(image, gray, template, floor, color_index, coarse)
            # The tracked player is near the window centre. Even offsets keep the coarse
            # slice identical to the whole window's proposals inside the area.
            x, y, w, h = area
            found = self._template_candidates(
                image[y : y + h, x : x + w], gray[y : y + h, x : x + w], template, floor,
                color_index, None if coarse is None
                else coarse[y // 2 : (y + h + 1) // 2, x // 2 : (x + w + 1) // 2])
            return [replace(item, box=item.box.translated(x, y)) for item in found]

        def match(batch: list[Template]) -> list[list[Detection]]:
            return self._sprite_batch(image, gray, batch, floor, color_index)

        # Catalog sprites match in batches; the batches and the other templates run in
        # parallel. Results keep template order.
        sprites = [template for template in usable if template.signature is not None]
        others = [template for template in usable if template.signature is None]
        batches = [sprites[start : start + SPRITE_BATCH]
                   for start in range(0, len(sprites), SPRITE_BATCH)]
        if len(batches) + len(others) > 1:
            pending = [self.pool.submit(match, batch) for batch in batches]
            other_results = list(self.pool.map(search, others))
            batch_results = [future.result() for future in pending]
        else:
            other_results = [search(template) for template in others]
            batch_results = [match(batch) for batch in batches]
        results = {id(template): found for template, found in zip(
            [*sprites, *others],
            [*(found for batch in batch_results for found in batch), *other_results],
            strict=True,
        )}
        return [candidate for template in usable for candidate in results[id(template)]]

    def _template_candidates(
        self, image: Image, gray: Image, template: Template, floor: float, color_index,
        coarse: Image | None = None,
    ) -> list[Detection]:
        if template.signature is not None:
            return self._sprite_candidates(image, gray, template, floor, color_index)
        if template.anchor is not None:
            return self._anchor_candidates(image, gray, template, floor, coarse)
        height, width = template.gray.shape
        candidates: list[Detection] = []
        # Color helps distinguish similar silhouettes; correlation adds local structure.
        structure = cv2.matchTemplate(gray, template.gray, cv2.TM_CCOEFF_NORMED)
        color = self._color_where_possible(image, template, structure, floor)
        score = np.nan_to_num(0.6 * color + 0.4 * structure, copy=False,
                              nan=0, posinf=0, neginf=0)
        for _ in range(self.config.max_candidates):
            _, peak, _, (x, y) = cv2.minMaxLoc(score)
            if peak < floor:
                break
            candidates.append(
                Detection(
                    template.kind,
                    Rect(x, y, width, height),
                    round(float(peak), 6),
                    template.name,
                )
            )
            score[
                max(0, y - height // 2) : y + height // 2 + 1,
                max(0, x - width // 2) : x + width // 2 + 1,
            ] = 0
        return candidates

    @staticmethod
    def _color_where_possible(
        image: Image, template: Template, structure: Image, floor: float
    ) -> Image:
        """1 - TM_SQDIFF_NORMED around positions whose structure can still reach the floor.

        Elsewhere color stays 0: weighted at most 0.6 it could not lift those positions to
        the floor, and the whole-frame color map is the slowest part of this search.
        """
        height, width = template.gray.shape
        color = np.zeros_like(structure)
        possible = np.uint8(structure >= (floor - COLOR_WEIGHT_CAP) / 0.4)
        _, _, stats, _ = cv2.connectedComponentsWithStats(possible)
        for x, y, w, h, _ in stats[1:]:
            color[y : y + h, x : x + w] = 1 - cv2.matchTemplate(
                image[y : y + h + height - 1, x : x + w + width - 1],
                template.image,
                cv2.TM_SQDIFF_NORMED,
            )
        return color

    def _uncover(self, image: Image, gray: Image, candidates: list[Detection],
                 templates: list[Template], player: Detection | None) -> list[Detection]:
        """Rescore near-miss monsters that this frame's player or monsters partly cover.

        Inside a covering box, pixels that differ from the sprite are ignored. Pixels outside
        every covering box are an unbiased check: 15% of the sprite must lie there and
        nearly all of it must match, so nothing is found inside a covering box alone.
        """
        confident = [item for item in candidates
                     if item.kind == "monster" and item.confidence >= self.config.confidence]
        # The player's box widened for a held weapon.
        cover = [Rect(player.box.x - 40, player.box.y - 8, player.box.width + 80,
                      player.box.height + 16)] if player else []
        named: dict[str, list[Template]] = {}
        for template in templates:
            named.setdefault(template.name, []).append(template)
        result = []
        for item in candidates:
            box = item.box
            boxes = cover + [other.box for other in confident if other.box.iou(box) < 0.5]
            if (item.kind != "monster" or item.confidence >= self.config.confidence
                    or not any(other.iou(box) > 0 for other in boxes)):
                result.append(item)
                continue
            # Mirrored variants share a name; keep the best uncovered score among them.
            best = max((self._uncovered_score(image, gray, template, box, boxes)
                        for template in named.get(item.template, [])), default=0.0)
            if best > item.confidence:
                item = replace(item, confidence=round(best, 6))
            result.append(item)
        return result

    def _uncovered_score(self, image: Image, gray: Image, template: Template, box: Rect,
                         boxes: list[Rect]) -> float:
        if template.anchor is None or template.mask is None:
            return 0.0
        anchor, mask = template.anchor, template.mask != 0
        top, left = box.y + anchor.y, box.x + anchor.x
        if (top < 0 or left < 0 or top + anchor.height > image.shape[0]
                or left + anchor.width > image.shape[1]):
            return 0.0
        zone = np.zeros(mask.shape, dtype=bool)
        for other in boxes:
            zone[max(0, other.y - top):max(0, other.y + other.height - top),
                 max(0, other.x - left):max(0, other.x + other.width - left)] = True
        crop = (slice(top, top + anchor.height), slice(left, left + anchor.width))
        region = (slice(anchor.y, anchor.y + anchor.height),
                  slice(anchor.x, anchor.x + anchor.width))
        difference = np.max(np.abs(image[crop].astype(np.int16)
                                   - template.image[region].astype(np.int16)), axis=2)
        visible = mask & ~(zone & (difference > 40))
        outside = mask & ~zone
        if (np.count_nonzero(visible) < 0.4 * np.count_nonzero(mask)
                or np.count_nonzero(outside) < 0.15 * np.count_nonzero(mask)
                or np.mean(difference[outside] <= 24) < 0.85):
            return 0.0
        return masked_score(
            image[crop][visible].astype(np.float32),
            gray[crop][visible].astype(np.float32),
            template.image[region][visible].astype(np.float32),
            template.gray[region][visible].astype(np.float32),
        )

    @staticmethod
    def _suppress(candidates: list[Detection]) -> list[Detection]:
        kept: list[Detection] = []
        for candidate in sorted(candidates, key=lambda item: item.confidence, reverse=True):
            # Duplicate monster matches overlap almost fully (IoU >= 0.7 in the Middle Forest
            # recordings); stacked monsters overlap less and must both survive.
            limit = 0.5 if candidate.kind == "monster" else 0.25
            if not any(
                item.kind == candidate.kind and item.box.iou(candidate.box) > limit for item in kept
            ):
                kept.append(candidate)
        return kept

    def _resolve(
        self,
        players: list[Detection],
        tags: list[tuple[Detection, NameTag]],
        failures: list[str],
        gray: Image,
        now: float | None = None,
    ) -> tuple[Detection | None, float, bool]:
        player = players[0] if players and players[0].confidence >= self.config.confidence else None
        confident = [item.box.center for item in players
                     if not item.tracked and item.confidence >= self.config.confidence]
        if now is not None and any(math.dist(a, b) >= LOOKALIKE_SEPARATION
                                   for a, b in combinations(confident, 2)):
            self.lookalike_at = now  # A second identical-looking player is in view.
        if player and len(players) > 1:
            if player.confidence - players[1].confidence < self.config.player_margin:
                player = None
                self.confirmed_sprites = ConfirmedSprites()
                failures.append("Ambiguous player: multiple similar matches")
        if not self.nametags:
            return player, 0.0, False
        return self._fuse_nametag(tags, player, failures, gray, now)

    def enemy_scan_feedback(self, frame_id: str, *, fresh: bool, eligible: bool) -> None:
        """Only independent, fresh runtime observations advance the empty-scan counter."""
        if frame_id == self.enemy_scan_frame:
            return
        self.enemy_scan_frame = frame_id
        if not fresh or eligible:
            self.enemy_empty_observations = 0
        else:
            self.enemy_empty_observations += 1

    def detect(self, image: Image, now: float | None = None, *,
               monsters: bool = True) -> Observation:
        """monsters=False searches only the player, for work that never targets an enemy."""
        now = time.monotonic() if now is None else now
        began = time.perf_counter()
        # Camera motion only needs the frame, so it runs beside recognition.
        camera = self.pool.submit(self.camera.update, image)
        floor = max(0.5, self.config.confidence - 0.15)
        allowed = self.map_filter.select(image, self.taught_map)
        # Searching every catalog species costs seconds per frame; wait for a readable map.
        paused = allowed is None and self.map_filter.required
        if paused:
            allowed = set()
        templates = self._active_templates(allowed, monsters)
        held = self.map_filter.held and self.map_filter.taught is not None
        self.catalog_info["active_map"] = (
            self.map_filter.taught[0] if held else self.map_filter.title
        )
        self.catalog_info["map_filter_held"] = held
        self.catalog_info["map_filter_error"] = self.map_filter.error
        self.catalog_info["spawn_source"] = self.map_filter.source
        self.catalog_info["spawn_revision"] = self.map_filter.revision
        self.catalog_info["spawn_error"] = (
            self.map_filter.source_error or self.map_filter.coverage_error
        ) or (
            "Map unsupported or title unreadable in selected spawn dataset"
            if paused and self.map_filter.source != "legacy-dream" else None
        )
        self.catalog_info["catalog_paused"] = paused
        self.catalog_info["active_variants"] = len(templates)
        scan_context = (self.enemy_source, self.catalog_info["active_map"],
                        self.map_filter.source, self.map_filter.revision, image.shape,
                        monsters, paused)
        if scan_context != self.enemy_scan_context:
            self.enemy_empty_observations = 0
            self.enemy_scan_frame = None
            self.enemy_tile = -1
            self.enemy_scan_context = scan_context
        self.enemy_scan_stage = "local"
        self.catalog_info["enemy_empty_observations"] = self.enemy_empty_observations
        waited = time.perf_counter()
        self._predict(*camera.result())
        searched = time.perf_counter()
        predicted = self.track[0] if self.track else None
        search_enemies = monsters
        player, monsters, failures, tag_confidence = self._observe_window(
            image, now, templates, floor, player_only=not monsters
        )
        self.enemy_cell = None
        if search_enemies and not paused:
            monsters, failures = self._scan_tile(image, templates, floor, player, monsters,
                                                 failures)
        self.catalog_info["enemy_scan_stage"] = self.enemy_scan_stage
        refreshed = time.perf_counter()
        self._learn_motion(now)
        self.previous_monsters = tuple(
            item.box for item in monsters if item.confidence >= self.config.confidence
        )
        if player and not player.tracked and tag_confidence >= REFRESH_TAG_CONFIDENCE:
            self._refresh_sprite(image, player, monsters, now)
        shift, response = camera.result()
        tracked = time.perf_counter()
        context = (self.enemy_source, self.catalog_info["active_map"], image.shape,
                   search_enemies, paused)
        if context != self.enemy_context:
            self.enemy_tracker.clear()
            self.enemy_geometry_ready = False
            self.enemy_geometry_retry_at = float("-inf")
            self.enemy_context = context
        if search_enemies and not paused:
            self.enemy_tracker.prepare(now, shift, response)
            self._configure_enemy_geometry(image, response, now)
            partials = partial_enemies(image, templates, self.enemy_tracker, monsters)
            monsters = self.enemy_tracker.update(monsters, now, partials)
        else:
            self.enemy_tracker.clear()
        finished = time.perf_counter()
        # Wall time per stage of this call, for profiling; never read by decisions.
        self.stage_ms = {key: round(value * 1000, 1) for key, value in (
            ("setup", waited - began), ("camera_wait", searched - waited),
            ("search", refreshed - searched), ("refresh", tracked - refreshed),
            ("enemies", finished - tracked))}
        return Observation(player, monsters, failures, shift, response,
                           self.enemy_tracker.snapshot(),
                           self._tracking_snapshot(player, predicted, now))

    def _tracking_snapshot(self, player: Detection | None, predicted: Rect | None,
                           now: float) -> dict:
        """State, predicted/observed boxes and search window for the debug overlay."""
        if player is not None:
            state = "tracked" if player.tracked else "confirmed"
        else:
            state = "coasting" if self.track is not None else "lost"
        named = player and (player.identity or (
            player.template.removesuffix(":tag-only")
            if player.template.startswith("nametag:") else None))
        return {
            "state": state,
            "predicted": asdict(predicted) if predicted else None,
            "observed": asdict(player.box) if player else None,
            "search": asdict(self.search_window) if self.search_window else None,
            # Monsters were also searched here this frame (one grid cell outside the window).
            "enemy_cell": asdict(self.enemy_cell) if self.enemy_cell else None,
            "confidence": round(float(player.confidence), 3) if player else 0.0,
            "identity": named or None,
            "since_confirmed": round(now - self.track[1], 3) if self.track else None,
        }

    def _configure_enemy_geometry(self, image: Image, response: float,
                                  now: float | None = None) -> None:
        """Bind saved rectangles to scenery using a screenshot, never a gameplay coordinate."""
        tracker = self.enemy_tracker
        if response < .6:
            tracker.regions, tracker.platforms = (), ()
            self.enemy_geometry_ready = False
        if self.enemy_geometry_ready:
            return
        now = time.monotonic() if now is None else now
        if now < self.enemy_geometry_retry_at:
            return
        entry = self.enemy_geometry.get(self.catalog_info["active_map"])
        if not entry:
            return
        # Failed optional reference alignment must not consume every frame's freshness
        # budget. Regions remain unavailable until a later attempt establishes geometry.
        self.enemy_geometry_retry_at = now + 1.0
        reference_path = (self.directory / entry["reference"]).resolve()
        if not reference_path.is_relative_to(self.directory.resolve()):
            raise ValueError("Enemy occlusion reference must be inside templates directory")
        reference = cv2.imread(str(reference_path), cv2.IMREAD_COLOR)
        if reference is None or reference.shape != image.shape:
            return
        camera = CameraTracker()
        camera.update(reference)
        shift, confidence = camera.update(image)
        if confidence < .6:
            return  # No trustworthy projection: ordinary short lost-track retention only.
        regions = entry.get("regions", [])
        if any(len(box) != 4 or not all(isinstance(v, int) for v in box) for box in regions):
            raise ValueError("Enemy occlusion regions require integer [x, y, width, height]")
        tracker.regions = tuple(Rect(*box) for box in regions)
        tracker.platforms = tuple(tuple(segment) for segment in entry.get("platforms", []))
        if any(len(p) != 4 or not all(np.isfinite(v) for v in p) or p[2] <= p[0]
               for p in tracker.platforms):
            raise ValueError("Enemy platforms require finite [x1, y1, x2, y2], x1 < x2")
        tracker.translate_geometry(*shift)
        self.enemy_geometry_ready = True

    def _predict(self, shift: tuple[float, float], response: float) -> None:
        """Move the last box to where the player should appear in this frame."""
        self.predicted = None
        if self.track is None:
            return
        if response < PREDICTION_RESPONSE:
            self.world_step = (0.0, 0.0)  # Unknown camera motion: search unshifted.
            return
        box, confirmed, seen = self.track
        self.predicted = (box, shift)
        self.confirmed_sprites.translate(*shift)
        self.track = (box.translated(self.world_step[0] + shift[0],
                                     self.world_step[1] + shift[1]), confirmed, seen)

    def _learn_motion(self, now: float) -> None:
        """Update the world motion from a box found in this frame; a miss keeps it."""
        if self.track is None or self.predicted is None:
            if self.track is None:
                self.world_step = (0.0, 0.0)
            return
        box, _, seen = self.track
        if seen != now:
            return
        (x0, y0), shift = self.predicted[0].center, self.predicted[1]
        x1, y1 = box.center
        self.world_step = tuple(
            float(np.clip(value, -PREDICTION_MAX_STEP, PREDICTION_MAX_STEP))
            for value in (x1 - x0 - shift[0], y1 - y0 - shift[1]))

    def _active_templates(self, allowed: set[str] | None, monsters: bool) -> list[Template]:
        """Templates for the allowed species; reused while the selection is unchanged."""
        key = (None if allowed is None else frozenset(allowed), monsters)
        if self.active is not None and self.active[0] is self.templates and self.active[1] == key:
            return self.active[2]
        templates = (
            self.templates
            if allowed is None
            else [
                template
                for template in self.templates
                if not template.name.startswith("catalog:")
                or template.name.split(":")[1] in allowed
            ]
        )
        if not monsters:
            templates = [template for template in templates if template.kind != "monster"]
        self.active = (self.templates, key, templates)
        return templates

    def _window(self, image: Image, *, player_only: bool = False) -> Rect | None:
        """Region around the tracked player, or None when the whole frame must be searched."""
        width, height = self.config.roi_width, self.config.roi_height
        if self.track is None or not width or not height:
            return None
        if player_only:
            # Movement does not need the surrounding enemy search area. A miss still
            # falls back to the complete frame with the same recognition thresholds.
            width, height = min(width, 350), min(height, 240)
        if width >= image.shape[1] and height >= image.shape[0]:
            return None
        cx, cy = self.track[0].center
        width, height = min(width, image.shape[1]), min(height, image.shape[0])
        x = min(max(0, round(cx - width / 2)), image.shape[1] - width)
        y = min(max(0, round(cy - height / 2)), image.shape[0] - height)
        return Rect(x, y, width, height)

    @staticmethod
    def _player_area(box: Rect, image: Image) -> tuple[int, int, int, int]:
        """The 350 x 240 movement window around the track, at even offsets inside the image."""
        width, height = min(350, image.shape[1]), min(240, image.shape[0])
        cx, cy = box.center
        x = min(max(0, round(cx - width / 2)), image.shape[1] - width) & ~1
        y = min(max(0, round(cy - height / 2)), image.shape[0] - height) & ~1
        return x, y, width, height

    def _observe_window(
        self, image: Image, now: float, templates: list[Template], floor: float,
        *, player_only: bool = False,
    ) -> tuple[Detection | None, list[Detection], list[str], float]:
        if self.verify_scan and self.track is not None:
            self.verify_scan, self.verifying = False, True
            try:
                return self._observe_full(image, now, templates, floor)
            finally:
                self.verifying = False
        window = self._window(image, player_only=player_only)
        self.origin = (0, 0)
        if window is None:
            return self._observe_full(image, now, templates, floor)
        saved = self.track
        assert saved is not None
        found = self._observe_in(image, window, now, templates, floor)
        if found[0] is not None:
            self.misses = self.full_scans = 0
            return found
        self.track = saved
        if not player_only and now - saved[1] <= self.config.track_max_seconds:
            # Keys are released while the player is unconfirmed, so it stays near the
            # prediction; scan the whole frame only on every FULL_SCAN_EVERY-th miss.
            self.misses += 1
            if self.misses % FULL_SCAN_EVERY:
                found[2].append("Player not found near its prediction; full scan deferred")
                return found
            return self._observe_full(image, now, templates, floor)
        if player_only and now - saved[1] <= self.config.track_seconds:
            # Shortly after a confirmed frame the player is near the prediction. Searching
            # the whole frame here takes about five times longer, which can push a recovery
            # frame past its freshness limit; it resumes once the track expires.
            wider = self._window(image)
            if wider is not None and wider != window:
                found = self._observe_in(image, wider, now, templates, floor)
            if found[0] is None:
                self.track = saved
                found[2].append("Player not found near the last confirmed position")
            return found
        return self._observe_full(image, now, templates, floor)

    def _set_occluders(self, shape: tuple[int, int], player: Rect | None,
                       origin: tuple[int, int]) -> None:
        """Covering zones for a searched image: the player box widened for a held weapon
        (already in that image's pixels) and previous monsters (frame pixels)."""
        ox, oy = origin
        self.occluders = ((Rect(player.x - 40, player.y - 8, player.width + 80,
                                player.height + 16),) if player else ()) + tuple(
            Rect(box.x - ox - 4, box.y - oy - 4, box.width + 8, box.height + 8)
            for box in self.previous_monsters)
        # Zone membership per pixel, and a summed table for "does a box touch a zone".
        self.zones = np.zeros(shape, dtype=np.uint8)
        for box in self.occluders:
            self.zones[max(0, box.y):max(0, box.y + box.height),
                       max(0, box.x):max(0, box.x + box.width)] = 1
        self.zone_sums = cv2.integral(self.zones)

    def _scan_tile(self, image: Image, templates: list[Template], floor: float,
                   player: Detection | None, monsters: list[Detection], failures: list[str],
                   ) -> tuple[list[Detection], list[str]]:
        """Monsters in the next grid cell outside this frame's search window.

        Cells are padded by the largest active sprite so a monster on a cell edge is
        still whole in one cell. The same candidate search and floor apply; only the
        player and name-tag searches are skipped there.
        """
        window = self.search_window
        height, width = image.shape[:2]
        species = [template for template in templates if template.kind == "monster"]
        if window is None or not species:
            return monsters, failures
        pad = min(120, max(max(template.image.shape[:2]) for template in species))
        cells = []
        for row in range(TILE_ROWS):
            for column in range(TILE_COLUMNS):
                x0, x1 = column * width // TILE_COLUMNS, (column + 1) * width // TILE_COLUMNS
                y0, y1 = row * height // TILE_ROWS, (row + 1) * height // TILE_ROWS
                if window.contains(Rect(x0, y0, x1 - x0, y1 - y0)):
                    continue  # The window search already covers this cell.
                left, top = max(0, x0 - pad), max(0, y0 - pad)
                right, bottom = min(width, x1 + pad), min(height, y1 + pad)
                cells.append((row * TILE_COLUMNS + column, Rect(left, top, right - left,
                                                                bottom - top)))
        if not cells:
            return monsters, failures
        index, cell = next(((key, cell) for key, cell in cells if key > self.enemy_tile),
                           cells[0])
        self.enemy_tile, self.enemy_scan_stage = index, f"tile {index + 1}/{len(cells)}"
        self.enemy_cell = cell
        crop = image[cell.y:cell.y + cell.height, cell.x:cell.x + cell.width]
        cache, area = self.masked_cache, self.player_area
        zones = self.occluders, self.zones, self.zone_sums
        self.player_area = None
        # Covering zones must match the cell's own size and pixels.
        self._set_occluders(crop.shape[:2], player.box.translated(-cell.x, -cell.y)
                            if player else None, (cell.x, cell.y))
        try:
            found = self._candidates(crop, cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), species, floor)
        finally:
            # The window search keeps its native-crop cache; a cell is not searched again soon.
            self.masked_cache, self.player_area = cache, area
            self.occluders, self.zones, self.zone_sums = zones
        extra = [replace(item, box=item.box.translated(cell.x, cell.y))
                 for item in self._suppress(found) if item.kind == "monster"]
        if not extra:
            return monsters, failures
        merged = [item for item in self._suppress([*monsters, *extra])
                  if not player or item.box.iou(player.box) < 0.5]
        failures = [failure for failure in failures if failure not in (
            "No visible monster template matches", "Monster matches below confidence threshold")]
        if not merged:
            failures.append("No visible monster template matches")
        elif not any(item.confidence >= self.config.confidence for item in merged):
            failures.append("Monster matches below confidence threshold")
        return merged, failures

    def _observe_in(
        self, image: Image, window: Rect, now: float, templates: list[Template], floor: float,
    ) -> tuple[Detection | None, list[Detection], list[str], float]:
        """Observe inside `window`; boxes come back in full-frame coordinates."""
        saved = self.track
        assert saved is not None
        local = (saved[0].translated(-window.x, -window.y), saved[1], saved[2])
        self.track = local
        crop = image[window.y : window.y + window.height, window.x : window.x + window.width]
        self.origin, self.search_window = (window.x, window.y), window
        # Player templates need only the movement-sized area around the track.
        self.player_area = self._player_area(local[0], crop)
        player, monsters, failures, tag_confidence = self._observe(crop, now, templates, floor)
        self.origin, self.player_area = (0, 0), None
        if self.track is not None:
            box, confirmed, seen = self.track
            self.track = (box.translated(window.x, window.y), confirmed, seen)

        def shifted(item: Detection) -> Detection:
            return replace(item, box=item.box.translated(window.x, window.y))

        return (shifted(player) if player else None,
                [shifted(item) for item in monsters], failures, tag_confidence)

    def _observe_full(
        self, image: Image, now: float, templates: list[Template], floor: float
    ) -> tuple[Detection | None, list[Detection], list[str], float]:
        """The whole frame, or only the strip the minimap marker leaves possible."""
        self.search_window = None
        if self.strip is None:
            return self._observe(image, now, templates, floor)
        x0, x1 = max(0, self.strip[0]), min(image.shape[1], self.strip[1])
        if x1 - x0 <= 0:
            return self._observe(image, now, templates, floor)
        self.search_window = Rect(x0, 0, x1 - x0, image.shape[0])
        if self.track is not None:
            box, confirmed, seen = self.track
            self.track = (box.translated(-x0, 0), confirmed, seen)
        self.origin = (x0, 0)
        player, monsters, failures, tag_confidence = self._observe(
            image[:, x0:x1], now, templates, floor)
        self.origin = (0, 0)
        if self.track is not None:
            box, confirmed, seen = self.track
            self.track = (box.translated(x0, 0), confirmed, seen)

        def shifted(item: Detection) -> Detection:
            return replace(item, box=item.box.translated(x0, 0))

        return (shifted(player) if player else None,
                [shifted(item) for item in monsters], failures, tag_confidence)

    def _observe(
        self, image: Image, now: float, templates: list[Template], floor: float
    ) -> tuple[Detection | None, list[Detection], list[str], float]:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        self._set_occluders(image.shape[:2], self.track[0] if self.track else None,
                            self.origin)
        # Name tags match in the pool while the sprite templates are searched.
        searches = self._nametag_search(gray)
        tag_area = self._tag_first_area(gray, searches, now)
        if tag_area is not None:
            self.player_area = tag_area
        candidates = self._candidates(image, gray, templates, floor)
        kept = self._suppress(candidates)
        players = [item for item in kept if item.kind == "player"]
        tags = self._nametag_candidates(gray, searches)
        failures: list[str] = []
        player, tag_confidence, conflict = self._resolve(players, tags, failures, gray, now)
        if player is None and not conflict and self.fresh:
            # Snapshots are only searched when the taught templates and the tag fall short.
            fresh = [item for group in self.fresh for item in group]
            kept = self._suppress(candidates + self._candidates(image, gray, fresh, floor))
            players = [item for item in kept if item.kind == "player"]
            failures = []
            player, tag_confidence, conflict = self._resolve(players, tags, failures, gray, now)
        if tag_area is not None:
            self.player_area = None
            self.verify_scan = player is not None and not conflict
        if conflict:
            self.conflict_at = now if now is not None else self.conflict_at
            self.confirmed_sprites = ConfirmedSprites()
            self.fresh.clear()
            self.track, self.track_tag = None, None
        elif player is not None:
            self.track = (player.box, now, now)
            if player.template.startswith("nametag:"):
                self.track_tag = player.template.split(":")[1]
        else:
            player = self._follow(gray, players, now, failures)
        if (player is not None and now is not None and player.identity is None
                and not player.template.startswith("nametag:")):
            # Tracked or weak sprite frames under foreground cover carry the name onward.
            self.confirmed_sprites.follow(
                player.box.translated(*self.origin), now, TRACK_MAX_RADIUS)
        if player is None:
            failures.append("Player detection missing or below confidence threshold")
        # With this frame's player known, rescore monsters it or other monsters partly cover.
        kept = self._suppress(self._uncover(image, gray, candidates, templates, player))
        monsters = [
            item
            for item in kept
            if item.kind == "monster" and (not player or item.box.iou(player.box) < 0.5)
        ]
        if not monsters:
            failures.append("No visible monster template matches")
        elif not any(item.confidence >= self.config.confidence for item in monsters):
            failures.append("Monster matches below confidence threshold")
        return player, monsters, failures, tag_confidence

    def _refresh_sprite(
        self, image: Image, player: Detection, monsters: list[Detection], now: float
    ) -> None:
        """Snapshot the sprite above a clean tag, so a new outfit is recognised in grass."""
        if self.fresh and now - self.refreshed < REFRESH_SECONDS:
            return
        body = player.box
        left, top = max(0, body.x - 16), max(0, body.y - 16)
        right, bottom = (
            min(image.shape[1], body.x + body.width + 16),
            min(image.shape[0], body.feet),
        )
        if right - left < 24 or bottom - top < 24:
            return
        region = Rect(left, top, right - left, bottom - top)
        if any(item.box.iou(region) > 0.05 for item in monsters):
            return  # A neighbouring sprite would become part of the player template.
        crop = image[top:bottom, left:right].copy()
        anchor, mask = self._player_anchor(crop)
        if anchor is None or mask is None:
            return
        variants = []
        for mirrored in (False, True):
            variant = cv2.flip(crop, 1) if mirrored else crop
            variant_anchor, variant_mask = anchor, mask
            if mirrored:
                variant_anchor = Rect(
                    crop.shape[1] - anchor.x - anchor.width, anchor.y, anchor.width, anchor.height
                )
                variant_mask = cv2.flip(mask, 1)
            variants.append(
                Template(
                    "player",
                    f"fresh:{round(now, 3)}",
                    variant,
                    cv2.cvtColor(variant, cv2.COLOR_BGR2GRAY),
                    variant_anchor,
                    variant_mask,
                )
            )
        self.fresh.append(variants)
        # These appearances were captured directly above a clean full name, unlike
        # unrelated taught poses encountered later during name occlusion.
        identity = f"nametag:{player.template.split(':')[1]}"
        for variant in variants:
            self.confirmed_sprites.names[variant.name] = identity
        self.refreshed = now

    def _follow(
        self, gray: Image, players: list[Detection], now: float, failures: list[str]
    ) -> Detection | None:
        """Accept weaker evidence only next to the last tracked position.

        Each frame with evidence extends the chain; a gap longer than track_seconds or a
        chain longer than track_max_seconds since the last confirmed frame ends it.
        """
        if self.track is None:
            return None
        last, confirmed, seen = self.track
        elapsed = now - confirmed
        if elapsed > self.config.track_max_seconds:
            self.track = None
            return None
        if now - seen > self.config.track_seconds:
            # Coasting: the search window stays on the prediction, but weaker evidence is
            # refused after the gap; only a confident match restarts the track.
            self.world_step = (0.0, 0.0)  # Recovery releases keys, so the player stops.
            failures.append("Player coasting at its predicted position; no fresh evidence")
            return None
        radius = min(TRACK_MAX_RADIUS, TRACK_RADIUS + TRACK_SPEED * (now - seen))
        near = [
            item
            for item in players
            if abs(item.box.center[0] - last.center[0]) <= radius
            and abs(item.box.feet - last.feet) <= radius + 30
        ]
        if len(near) > 1:
            failures.append("Ambiguous player near last confirmed position")
            return None
        box, confidence = (near[0].box, near[0].confidence) if near else (None, 0.0)
        for tag in (tag for tag in self.nametags if tag.name == self.track_tag):
            score, body = self._partial_nametag(gray, tag, last, radius)
            if body is not None and score >= self.config.nametag_partial:
                # The tag fixes the feet more precisely than a loose sprite box.
                box, confidence = body, max(confidence, score)
                break
        if box is None:
            return None
        self.track = (box, confirmed, now)
        failures.append(f"Player tracked from last confirmed position ({elapsed:.1f}s ago)")
        return Detection("player", box, round(confidence, 6), "tracked", tracked=True)

    def _partial_nametag(
        self, gray: Image, tag: NameTag, last: Rect, radius: float
    ) -> tuple[float, Rect | None]:
        """Tag score near where the tag should be, tolerating partial cover."""
        height, width = tag.text.shape
        x = round(last.center[0] - width / 2)
        y = round(last.feet + NAMETAG_FEET_GAP - tag.text_top)
        reach = int(radius)
        left, top = max(0, x - reach), max(0, y - reach)
        right = min(gray.shape[1], x + width + reach)
        bottom = min(gray.shape[0], y + height + reach)
        if right - left < width or bottom - top < height:
            return 0.0, None
        score = text_overlap(gray[top:bottom, left:right], tag.text)
        _, best, _, (dx, dy) = cv2.minMaxLoc(score)
        box = Rect(left + dx - (width - 1), top + dy, width, height)
        return float(best), self.body_from_nametag(tag, box)

    def _tag_first_area(self, gray: Image, searches: list[Future[list[Detection]]],
                        now: float | None) -> tuple[int, int, int, int] | None:
        """On a whole-frame search, the movement window under one confident name tag.

        Player poses then search only there, which is several times faster. A look-alike
        or a sprite away from the tag is seen only by a whole-frame search, so every
        FULL_SCAN_EVERY-th one stays whole, as do all of them for RECOVERY_SECONDS after a
        look-alike or a name/sprite conflict, and whenever no single tag is confident.
        """
        if self.player_area is not None or self.verifying or now is None or not self.nametags:
            return None
        self.full_scans += 1
        if (self.full_scans % FULL_SCAN_EVERY == 0
                or now - self.lookalike_at < RECOVERY_SECONDS
                or now - self.conflict_at < RECOVERY_SECONDS):
            return None
        confident = [(match, tag) for match, tag in self._nametag_candidates(gray, searches)
                     if match.confidence >= self.config.nametag_confidence]
        if len(confident) != 1:
            return None
        match, tag = confident[0]
        return self._player_area(self.body_from_nametag(tag, match.box), gray)

    def _nametag_search(self, gray: Image) -> list[Future[list[Detection]]]:
        """Start matching every name tag in the pool, in self.nametags order."""
        floor = max(0.5, self.config.nametag_confidence - 0.15)
        near_white = np.float32(gray >= NAMETAG_TEXT)
        return [self.pool.submit(self.nametag_matches, gray, tag, floor, near_white)
                for tag in self.nametags]

    def _nametag_candidates(
        self, gray: Image, searches: list[Future[list[Detection]]] | None = None
    ) -> list[tuple[Detection, NameTag]]:
        searches = self._nametag_search(gray) if searches is None else searches
        matches = sorted(
            (
                (match, tag)
                for tag, search in zip(self.nametags, searches, strict=True)
                for match in search.result()
            ),
            key=lambda item: item[0].confidence,
            reverse=True,
        )
        distinct: list[tuple[Detection, NameTag]] = []
        for match, tag in matches:
            if not any(match.box.iou(other.box) > 0.25
                       and (tag.name == other_tag.name
                            or np.array_equal(tag.text, other_tag.text)
                            or other.confidence >= self.config.nametag_confidence)
                       for other, other_tag in distinct):
                distinct.append((match, tag))
        return distinct

    def _fuse_nametag(
        self,
        distinct: list[tuple[Detection, NameTag]],
        sprite: Detection | None,
        failures: list[str],
        gray: Image,
        now: float | None = None,
    ) -> tuple[Detection | None, float, bool]:
        """Returns the player, the tag confidence used, and whether tag and sprite conflict."""
        # The name tag survives gear changes and climbing poses; the sprite cross-checks it.
        partial_score = (self._occluded_tag_score(gray, distinct[0][1], distinct[0][0].box)
                         if distinct and sprite and not sprite.tracked
                         and distinct[0][0].confidence < self.config.nametag_confidence else 0)
        partial = partial_score >= self.config.nametag_confidence
        if not distinct or (distinct[0][0].confidence < self.config.nametag_confidence
                            and not partial):
            if sprite:
                failures.append("Name tag not found; located by player sprite")
                if (now is not None and now - self.lookalike_at < RECOVERY_SECONDS):
                    failures.append("Look-alike player nearby; name tag required for identity")
                elif (now is not None and not sprite.tracked
                        and sprite.confidence >= self.config.confidence):
                    identity = self.confirmed_sprites.resolve(
                        sprite.template, sprite.box.translated(*self.origin), now, TRACK_MAX_RADIUS)
                    if identity:
                        sprite = replace(sprite, identity=identity)
                        failures.append("Fresh sprite corroborated by recent full-name agreement")
                    elif (sprite.template not in self.confirmed_sprites.names
                          and self.confirmed_sprites.last is not None):
                        # Do not let _follow or positional tracking carry this unverified
                        # body into the named chain after identity resolution refused it.
                        failures.append("Unverified displaced sprite; name required for identity")
                        return None, 0.0, True
            return sprite, 0.0, False
        match, tag = distinct[0]
        if len(distinct) > 1 and match.confidence - distinct[1][0].confidence < (
            self.config.player_margin
        ):
            self.confirmed_sprites = ConfirmedSprites()
            failures.append("Ambiguous name tag: multiple similar matches")
            return sprite, 0.0, False
        body = self.body_from_nametag(tag, match.box)
        if sprite:
            near = (
                body.x - 12 <= sprite.box.center[0] <= body.x + body.width + 12
                and abs(sprite.box.feet - body.feet) <= 40
            )
            if not near:
                previous = self.confirmed_sprites.last
                # A fresh full name at the established position is independent identity
                # evidence. A spatially separate sprite must not replace that player or
                # become its learned appearance. Cold, moved and partial names still veto.
                # A name confirmed by a tag-first frame saw only its window, so it is
                # still cold during the whole-frame check that follows.
                continuous_name = (
                    not partial and not self.verifying and now is not None
                    and previous is not None
                    and previous[0] == f"nametag:{tag.name}"
                    and 0 <= now - previous[2] <= 1
                    and math.dist(body.translated(*self.origin).center,
                                  previous[1].center) <= 24
                )
                if not continuous_name:
                    failures.append("Name tag and player sprite disagree")
                    return None, match.confidence, True
                self.lookalike_at = now
                sprite = None
                failures.append("Separate sprite ignored; full name confirms established player")
        confidence = (min(partial_score, sprite.confidence) if partial else
                      max(match.confidence, sprite.confidence if sprite else 0))
        if partial:
            failures.append("Occluded name corroborated by fresh player sprite")
        name = f"nametag:{tag.name}"
        if now is not None and not partial:
            known_sprite = (sprite.template if sprite and not sprite.tracked
                            and sprite.confidence >= self.config.confidence else None)
            self.confirmed_sprites.observe(
                name, known_sprite, body.translated(*self.origin), now)
        if not sprite:
            failures.append("Player sprite not matched; located by name tag")
            name += ":tag-only"
        return Detection("player", body, round(confidence, 6), name), match.confidence, False

    def _occluded_tag_score(self, gray: Image, tag: NameTag, box: Rect) -> float:
        """Visible glyph precision, requiring evidence across both halves of the name.

        Only a fresh, independently matched sprite may corroborate this score. It never
        refreshes a sprite or turns positional tracking into identity evidence.
        """
        if box.x < 0 or box.y < 0 or box.x + box.width > gray.shape[1] or box.feet > gray.shape[0]:
            return 0
        observed = gray[box.y:box.y + box.height, box.x:box.x + box.width] >= NAMETAG_TEXT
        expected = tag.text > 0
        shared = observed & expected
        if shared.sum() < self.config.nametag_partial * expected.sum():
            return 0
        middle = box.width // 2
        for part in (slice(None, middle), slice(middle, None)):
            count = expected[:, part].sum()
            if not count or shared[:, part].sum() < .5 * count:
                return 0
        return float(shared.sum() / max(1, observed.sum()))


def annotate(
    image: Image, observation: Observation, target: Detection | None, state: str, reason: str
) -> Image:
    output = image.copy()
    entities = ([observation.player] if observation.player else []) + observation.monsters
    for entity in entities:
        box = entity.box
        color = (90, 220, 140) if entity.kind == "player" else (100, 170, 245)
        if target and box.iou(target.box) > 0.5:
            color = (50, 245, 245)
        cv2.rectangle(output, (box.x, box.y), (box.x + box.width, box.y + box.height), color, 2)
        label = (
            entity.template.split(":")[1] if entity.template.startswith("catalog:") else entity.kind
        )
        cv2.putText(
            output,
            f"{label} {entity.confidence:.2f}",
            (box.x, max(15, box.y - 5)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            color,
            1,
            cv2.LINE_AA,
        )
    for track in observation.enemy_tracks:
        x, y = map(round, track.predicted_position)
        ux, uy = map(round, track.uncertainty)
        color = (100, 170, 245) if track.state == "visible" else (180, 170, 130)
        cv2.ellipse(output, (x, y), (ux, uy), 0, 0, 360, color, 1)
        cv2.drawMarker(output, (x, y), color, cv2.MARKER_CROSS, 8, 1)
        cv2.putText(output, f"{track.track_id} {track.state} {track.confidence:.2f} "
                    f"+/-{ux},{uy}" + (" predicted" if not track.observed else ""),
                    (x + 5, max(15, y + 16)), cv2.FONT_HERSHEY_SIMPLEX, .35, color, 1)
    return output
