"""Replaceable perception using only operator-captured screenshot templates."""

import hashlib
import json
import os
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Protocol

import cv2
import numpy as np

from .capture import Image
from .config import PerceptionConfig
from .geometry import Rect
from .map_filter import MapFilter


@dataclass(frozen=True)
class Detection:
    kind: str
    box: Rect
    confidence: float
    template: str = ""
    # Accepted below the confidence threshold because it is close to the last confirmed
    # position; see TemplateDetector._follow.
    tracked: bool = False


@dataclass(frozen=True)
class Observation:
    player: Detection | None
    monsters: list[Detection]
    failures: list[str] = field(default_factory=list)
    camera_shift: tuple[float, float] = (0, 0)
    camera_confidence: float = 0


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


@dataclass(frozen=True)
class Template:
    kind: str
    name: str
    image: Image
    gray: Image
    anchor: Rect | None = None
    mask: Image | None = None
    signature: SpriteSignature | None = None


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
# Search radius around the last confirmed position: base plus walking speed, capped.
TRACK_RADIUS, TRACK_SPEED, TRACK_MAX_RADIUS = 12, 240, 80


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


def text_overlap(gray: Image, text: Image) -> Image:
    """F1 overlap between the glyph mask and near-white pixels at every position.

    The frame is padded left and right so a tag running off the edge still scores; its
    hidden glyphs count as missing. Index x maps to tag x - (width - 1).
    """
    height, width = text.shape
    observed = cv2.copyMakeBorder(
        np.float32(gray >= NAMETAG_TEXT), 0, 0, width - 1, width - 1, cv2.BORDER_CONSTANT, value=0
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

    def update(self, image: Image) -> tuple[tuple[float, float], float]:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        small = cv2.resize(gray, None, fx=0.5, fy=0.5).astype(np.float32)
        previous, self.previous = self.previous, small
        if previous is None or previous.shape != small.shape or float(small.std()) < 2:
            return (0, 0), 0
        window = cv2.createHanningWindow((small.shape[1], small.shape[0]), cv2.CV_32F)
        (dx, dy), response = cv2.phaseCorrelate(previous, small, window)
        if not np.isfinite([dx, dy, response]).all() or response < 0.35:
            return (0, 0), 0
        if abs(dx * 2) > image.shape[1] * 0.2 or abs(dy * 2) > image.shape[0] * 0.2:
            return (0, 0), 0
        return (dx * 2, dy * 2), float(response)


class TemplateDetector:
    def __init__(self, directory: Path, config: PerceptionConfig) -> None:
        self.directory, self.config = directory, config
        self.templates: list[Template] = []
        self.nametags: list[NameTag] = []
        # Sprites snapshotted from frames where the tag confirmed the player; memory only.
        self.fresh: deque[list[Template]] = deque(maxlen=2)
        self.refreshed = float("-inf")
        # Last position, when it was last confirmed, and when evidence last supported it.
        self.track: tuple[Rect, float, float] | None = None
        # Previous confident monster boxes (full frame) and the current search origin.
        # Together with the player track they mark pixels that may cover a sprite.
        self.previous_monsters: tuple[Rect, ...] = ()
        self.origin = (0, 0)
        # Columns (x0, x1) that replace the whole-frame fallback while the minimap marker
        # pins the player to one screen edge; thresholds are unchanged.
        self.strip: tuple[int, int] | None = None
        self.occluders: tuple[Rect, ...] = ()
        self.zones = np.zeros((1, 1), dtype=np.uint8)
        self.zone_sums = cv2.integral(self.zones)
        self.camera = CameraTracker()
        # Set by the runtime when the taught area's minimap confirms the current map.
        self.taught_map = False
        self.pool = ThreadPoolExecutor(
            max_workers=min(8, os.cpu_count() or 1), thread_name_prefix="match"
        )
        self.reload()

    def reload(self) -> None:
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
        self.map_filter = MapFilter(self.directory, list(entries.values()),
                                    self.config.spawn_source, self.config.spawn_revision)
        self.nametags = [
            self.load_nametag(path) for path in sorted((self.directory / "nametag").glob("*.png"))
        ]
        self.fresh.clear()
        self.track = None
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

    def nametag_matches(self, gray: Image, tag: NameTag, floor: float) -> list[Detection]:
        """Glyph-shape matches. Text on a light background (chat rows, clouds outside
        the box) adds near-white pixels around the glyphs and lowers the score."""
        height, width = tag.text.shape
        if height > gray.shape[0] or width > gray.shape[1]:
            return []
        score = text_overlap(gray, tag.text)
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
    def _color_index(image: Image) -> tuple[np.ndarray, np.ndarray]:
        colors = image.astype(np.uint16) >> 4
        codes = ((colors[:, :, 0] << 8) | (colors[:, :, 1] << 4) | colors[:, :, 2]).ravel()
        order = np.argsort(codes, kind="stable")
        boundaries = np.concatenate(([0], np.cumsum(np.bincount(codes, minlength=4096))))
        return order, boundaries

    def _sprite_candidates(
        self,
        image: Image,
        gray: Image,
        template: Template,
        floor: float,
        index: tuple[np.ndarray, np.ndarray],
    ) -> list[Detection]:
        signature, anchor = template.signature, template.anchor
        assert signature is not None and anchor is not None and template.mask is not None
        order, boundaries = index
        sizes = [int((boundaries[bins + 1] - boundaries[bins]).sum()) for bins in signature.buckets]
        ranked = np.argsort(sizes)
        # These sparse, color-selected samples are not an area/confidence estimate.
        # A few covered samples can still leave a strong full-mask match below.
        max_misses = (len(signature.colors) + 4) // 5
        # Sprites next to the player or a previous monster may be partly covered. There,
        # more samples may miss, and verification uses only the uncovered pixels.
        occluders = self.occluders
        relaxed = max(max_misses, len(signature.colors) // 2) if occluders else max_misses
        height, width = template.image.shape[:2]

        sums = self.zone_sums

        def covered(ys: np.ndarray, xs: np.ndarray) -> np.ndarray:
            if not occluders:
                return np.zeros(len(xs), dtype=bool)
            bottom = np.minimum(ys + height, sums.shape[0] - 1)
            right = np.minimum(xs + width, sums.shape[1] - 1)
            return (sums[bottom, right] - sums[ys, right] - sums[bottom, xs] + sums[ys, xs]) > 0

        proposals = []
        # Multiple seeds keep a covered proposal pixel from hiding an otherwise valid sprite.
        # Three extra seeds are enough to find the visible part of a covered sprite.
        for rank, key in enumerate(ranked[: max_misses + (4 if occluders else 1)]):
            buckets = [
                order[boundaries[b] : boundaries[b + 1]]
                for b in signature.buckets[key]
                if boundaries[b + 1] > boundaries[b]
            ]
            if not buckets:
                continue
            pixels = np.concatenate(buckets)
            ys = pixels // image.shape[1] - signature.offsets[key, 0]
            xs = pixels % image.shape[1] - signature.offsets[key, 1]
            valid = (
                (ys >= 0)
                & (xs >= 0)
                & (ys + template.image.shape[0] <= image.shape[0])
                & (xs + template.image.shape[1] <= image.shape[1])
            )
            if rank > max_misses:
                # Extra seeds only matter where something may cover the sprite.
                valid &= covered(ys, xs)
            proposals.append(ys[valid] * image.shape[1] + xs[valid])
        if not proposals:
            return []
        positions = np.unique(np.concatenate(proposals))
        ys, xs = positions // image.shape[1], positions % image.shape[1]
        near = covered(ys, xs)
        misses = np.zeros(len(xs), dtype=np.uint8)
        unexplained = np.zeros(len(xs), dtype=np.uint8)
        # Indexed color patterns propose exact native-pixel positions; full masks verify them.
        for key in ranked:
            if not len(xs):
                return []
            dy, dx = signature.offsets[key]
            delta = image[ys + dy, xs + dx].astype(np.int16) - signature.colors[key]
            wrong = np.max(np.abs(delta), axis=1) > 12
            misses += wrong
            if near.any():
                # A differing sample inside a covering zone is explained, not a miss.
                wrong &= self.zones[ys + dy, xs + dx] == 0
            unexplained += wrong
            valid = (unexplained <= max_misses) & (misses <= relaxed)
            ys, xs, near = ys[valid], xs[valid], near[valid]
            misses, unexplained = misses[valid], unexplained[valid]
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
        reference = template.image[
            anchor.y : anchor.y + anchor.height, anchor.x : anchor.x + anchor.width
        ]
        reference_gray = template.gray[
            anchor.y : anchor.y + anchor.height, anchor.x : anchor.x + anchor.width
        ]
        # Half-resolution grayscale proposals, then masked verification in native crops.
        coarse = cv2.pyrDown(gray) if coarse is None else coarse
        reference_coarse = cv2.pyrDown(reference_gray)
        if (reference_coarse.shape[0] > coarse.shape[0]
                or reference_coarse.shape[1] > coarse.shape[1]):
            return []
        proposals = cv2.matchTemplate(coarse, reference_coarse, cv2.TM_CCOEFF_NORMED)
        proposals = np.nan_to_num(proposals, nan=-1, posinf=-1, neginf=-1)
        found = []
        bounds = Rect(0, 0, image.shape[1], image.shape[0])
        for _ in range(self.config.max_candidates):
            _, peak, _, (cx, cy) = cv2.minMaxLoc(proposals)
            if peak < 0.25:
                break
            x, y = cx * 2, cy * 2
            left, top = max(0, x - 4), max(0, y - 4)
            right = min(image.shape[1], x + anchor.width + 4)
            bottom = min(image.shape[0], y + anchor.height + 4)
            color = 1 - cv2.matchTemplate(
                image[top:bottom, left:right], reference, cv2.TM_SQDIFF_NORMED, mask=template.mask
            )
            structure = cv2.matchTemplate(
                gray[top:bottom, left:right],
                reference_gray,
                cv2.TM_CCOEFF_NORMED,
                mask=template.mask,
            )
            score = np.nan_to_num(0.6 * color + 0.4 * structure, nan=0, posinf=0, neginf=0)
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
        color_index = (
            self._color_index(image)
            if any(template.signature is not None for template in usable) else None
        )

        coarse = cv2.pyrDown(gray) if any(t.anchor is not None for t in usable) else None

        def search(template: Template) -> list[Detection]:
            return self._template_candidates(image, gray, template, floor, color_index, coarse)

        # OpenCV releases the GIL, so templates match in parallel; map keeps template order.
        results = self.pool.map(search, usable) if len(usable) > 1 else map(search, usable)
        return [candidate for found in results for candidate in found]

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
        color = 1 - cv2.matchTemplate(image, template.image, cv2.TM_SQDIFF_NORMED)
        structure = cv2.matchTemplate(gray, template.gray, cv2.TM_CCOEFF_NORMED)
        score = np.nan_to_num(0.6 * color + 0.4 * structure, nan=0, posinf=0, neginf=0)
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
    ) -> tuple[Detection | None, float, bool]:
        player = players[0] if players and players[0].confidence >= self.config.confidence else None
        if player and len(players) > 1:
            if player.confidence - players[1].confidence < self.config.player_margin:
                player = None
                failures.append("Ambiguous player: multiple similar matches")
        if not self.nametags:
            return player, 0.0, False
        return self._fuse_nametag(tags, player, failures)

    def detect(self, image: Image, now: float | None = None, *,
               monsters: bool = True) -> Observation:
        """monsters=False searches only the player, for work that never targets an enemy."""
        now = time.monotonic() if now is None else now
        floor = max(0.5, self.config.confidence - 0.15)
        allowed = self.map_filter.select(image, self.taught_map)
        # Searching every catalog species costs seconds per frame; wait for a readable map.
        paused = allowed is None and self.map_filter.required
        if paused:
            allowed = set()
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
        player, monsters, failures, tag_confidence = self._observe_window(
            image, now, templates, floor, player_only=not monsters
        )
        self.previous_monsters = tuple(
            item.box for item in monsters if item.confidence >= self.config.confidence
        )
        if player and not player.tracked and tag_confidence >= REFRESH_TAG_CONFIDENCE:
            self._refresh_sprite(image, player, monsters, now)
        shift, response = self.camera.update(image)
        return Observation(player, monsters, failures, shift, response)

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

    def _observe_window(
        self, image: Image, now: float, templates: list[Template], floor: float,
        *, player_only: bool = False,
    ) -> tuple[Detection | None, list[Detection], list[str], float]:
        window = self._window(image, player_only=player_only)
        self.origin = (0, 0)
        if window is None:
            return self._observe_full(image, now, templates, floor)
        saved = self.track
        assert saved is not None
        local = (saved[0].translated(-window.x, -window.y), saved[1], saved[2])
        self.track = local
        crop = image[window.y : window.y + window.height, window.x : window.x + window.width]
        self.origin = (window.x, window.y)
        player, monsters, failures, tag_confidence = self._observe(crop, now, templates, floor)
        self.origin = (0, 0)
        if player is None:
            self.track = saved  # Lost inside the window: search the whole frame.
            return self._observe_full(image, now, templates, floor)
        if self.track is not None:
            box, confirmed, seen = self.track
            self.track = (box.translated(window.x, window.y), confirmed, seen)

        def shifted(item: Detection) -> Detection:
            return replace(item, box=item.box.translated(window.x, window.y))

        return shifted(player), [shifted(item) for item in monsters], failures, tag_confidence

    def _observe_full(
        self, image: Image, now: float, templates: list[Template], floor: float
    ) -> tuple[Detection | None, list[Detection], list[str], float]:
        """The whole frame, or only the strip the minimap marker leaves possible."""
        if self.strip is None:
            return self._observe(image, now, templates, floor)
        x0, x1 = max(0, self.strip[0]), min(image.shape[1], self.strip[1])
        if x1 - x0 <= 0:
            return self._observe(image, now, templates, floor)
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
        ox, oy = self.origin
        # Covering zones: the player box widened for a held weapon, and previous monsters.
        player = self.track[0] if self.track else None
        self.occluders = ((Rect(player.x - 40, player.y - 8, player.width + 80,
                                player.height + 16),) if player else ()) + tuple(
            Rect(box.x - ox - 4, box.y - oy - 4, box.width + 8, box.height + 8)
            for box in self.previous_monsters)
        # Zone membership per pixel, and a summed table for "does a box touch a zone".
        self.zones = np.zeros(image.shape[:2], dtype=np.uint8)
        for box in self.occluders:
            self.zones[max(0, box.y):max(0, box.y + box.height),
                       max(0, box.x):max(0, box.x + box.width)] = 1
        self.zone_sums = cv2.integral(self.zones)
        candidates = self._candidates(image, gray, templates, floor)
        kept = self._suppress(candidates)
        players = [item for item in kept if item.kind == "player"]
        tags = self._nametag_candidates(gray)
        failures: list[str] = []
        player, tag_confidence, conflict = self._resolve(players, tags, failures)
        if player is None and not conflict and self.fresh:
            # Snapshots are only searched when the taught templates and the tag fall short.
            fresh = [item for group in self.fresh for item in group]
            kept = self._suppress(candidates + self._candidates(image, gray, fresh, floor))
            players = [item for item in kept if item.kind == "player"]
            failures = []
            player, tag_confidence, conflict = self._resolve(players, tags, failures)
        if conflict:
            self.fresh.clear()
            self.track = None
        elif player is not None:
            self.track = (player.box, now, now)
        else:
            player = self._follow(gray, players, now, failures)
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
        if now - seen > self.config.track_seconds or elapsed > self.config.track_max_seconds:
            self.track = None
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
        for tag in self.nametags:
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

    def _nametag_candidates(self, gray: Image) -> list[tuple[Detection, NameTag]]:
        floor = max(0.5, self.config.nametag_confidence - 0.15)
        matches = sorted(
            (
                (match, tag)
                for tag in self.nametags
                for match in self.nametag_matches(gray, tag, floor)
            ),
            key=lambda item: item[0].confidence,
            reverse=True,
        )
        distinct: list[tuple[Detection, NameTag]] = []
        for match, tag in matches:
            if not any(match.box.iou(other.box) > 0.25 for other, _ in distinct):
                distinct.append((match, tag))
        return distinct

    def _fuse_nametag(
        self,
        distinct: list[tuple[Detection, NameTag]],
        sprite: Detection | None,
        failures: list[str],
    ) -> tuple[Detection | None, float, bool]:
        """Returns the player, the tag confidence used, and whether tag and sprite conflict."""
        # The name tag survives gear changes and climbing poses; the sprite cross-checks it.
        if not distinct or distinct[0][0].confidence < self.config.nametag_confidence:
            if sprite:
                failures.append("Name tag not found; located by player sprite")
            return sprite, 0.0, False
        match, tag = distinct[0]
        if len(distinct) > 1 and match.confidence - distinct[1][0].confidence < (
            self.config.player_margin
        ):
            failures.append("Ambiguous name tag: multiple similar matches")
            return sprite, 0.0, False
        body = self.body_from_nametag(tag, match.box)
        if sprite:
            near = (
                body.x - 12 <= sprite.box.center[0] <= body.x + body.width + 12
                and abs(sprite.box.feet - body.feet) <= 40
            )
            if not near:
                failures.append("Name tag and player sprite disagree")
                return None, match.confidence, True
        confidence = max(match.confidence, sprite.confidence if sprite else 0)
        name = f"nametag:{tag.name}"
        if not sprite:
            failures.append("Player sprite not matched; located by name tag")
            name += ":tag-only"
        return Detection("player", body, round(confidence, 6), name), match.confidence, False


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
    return output
