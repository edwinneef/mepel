"""Replaceable perception using only operator-captured screenshot templates."""

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import cv2
import numpy as np

from .capture import Image
from .config import PerceptionConfig
from .geometry import Rect


@dataclass(frozen=True)
class Detection:
    kind: str
    box: Rect
    confidence: float
    template: str = ""


@dataclass(frozen=True)
class Observation:
    player: Detection | None
    monsters: list[Detection]
    failures: list[str] = field(default_factory=list)
    camera_shift: tuple[float, float] = (0, 0)
    camera_confidence: float = 0


class Detector(Protocol):
    def detect(self, image: Image) -> Observation: ...


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
        self.camera = CameraTracker()
        self.reload()

    def reload(self) -> None:
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
                raw = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
                if raw is None or raw.ndim != 3 or raw.shape[2] not in (3, 4):
                    raise ValueError(f"Unreadable template: {path}")
                image = raw[:, :, :3].copy()
                self.validate(image)
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
                    if digest in seen_catalog:
                        continue
                    seen_catalog.add(digest)
                    name = f"catalog:{entry['name']}:{entry['animation']}-{entry['frame']}"
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
                    templates.append(
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
        self.templates = templates
        self.camera = CameraTracker()
        self.catalog_info = {
            "species": len(catalog_names),
            "frames": catalog_frames,
            "names": sorted(catalog_names),
            "network_during_detection": False,
        }

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
        if sizes[int(ranked[0])] == 0:
            return []
        key = int(ranked[0])
        pixels = np.concatenate(
            [
                order[boundaries[b] : boundaries[b + 1]]
                for b in signature.buckets[key]
                if boundaries[b + 1] > boundaries[b]
            ]
        )
        ys = pixels // image.shape[1] - signature.offsets[key, 0]
        xs = pixels % image.shape[1] - signature.offsets[key, 1]
        valid = (
            (ys >= 0)
            & (xs >= 0)
            & (ys + template.image.shape[0] <= image.shape[0])
            & (xs + template.image.shape[1] <= image.shape[1])
        )
        ys, xs = ys[valid], xs[valid]
        # Indexed color patterns propose exact native-pixel positions; full masks verify them.
        for key in ranked:
            if not len(xs):
                return []
            dy, dx = signature.offsets[key]
            delta = image[ys + dy, xs + dx].astype(np.int16) - signature.colors[key]
            valid = np.max(np.abs(delta), axis=1) <= 12
            ys, xs = ys[valid], xs[valid]
        mask = template.mask != 0
        reference = template.image[
            anchor.y : anchor.y + anchor.height, anchor.x : anchor.x + anchor.width
        ][mask].astype(np.float32)
        reference_gray = template.gray[
            anchor.y : anchor.y + anchor.height, anchor.x : anchor.x + anchor.width
        ][mask].astype(np.float32)
        centered = reference_gray - reference_gray.mean()
        energy = float((reference * reference).sum())
        found = []
        for x, y in zip(xs, ys, strict=True):
            observed = image[
                y + anchor.y : y + anchor.y + anchor.height,
                x + anchor.x : x + anchor.x + anchor.width,
            ][mask].astype(np.float32)
            observed_gray = gray[
                y + anchor.y : y + anchor.y + anchor.height,
                x + anchor.x : x + anchor.x + anchor.width,
            ][mask].astype(np.float32)
            color = 1 - float(((observed - reference) ** 2).sum()) / max(
                1e-6, np.sqrt(energy * float((observed * observed).sum()))
            )
            centered_observed = observed_gray - observed_gray.mean()
            structure = float(centered @ centered_observed) / max(
                1e-6, float(np.linalg.norm(centered) * np.linalg.norm(centered_observed))
            )
            confidence = float(np.clip(0.6 * color + 0.4 * structure, 0, 1))
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
    ) -> list[Detection]:
        anchor = template.anchor
        assert anchor is not None and template.mask is not None
        reference = template.image[
            anchor.y : anchor.y + anchor.height, anchor.x : anchor.x + anchor.width
        ]
        reference_gray = template.gray[
            anchor.y : anchor.y + anchor.height, anchor.x : anchor.x + anchor.width
        ]
        # Fast grayscale proposals, then masked verification in small native-resolution crops.
        proposals = cv2.matchTemplate(gray, reference_gray, cv2.TM_CCOEFF_NORMED)
        proposals = np.nan_to_num(proposals, nan=-1, posinf=-1, neginf=-1)
        found = []
        bounds = Rect(0, 0, image.shape[1], image.shape[0])
        for _ in range(self.config.max_candidates):
            _, peak, _, (x, y) = cv2.minMaxLoc(proposals)
            if peak < 0.25:
                break
            left, top = max(0, x - 3), max(0, y - 3)
            right = min(image.shape[1], x + anchor.width + 3)
            bottom = min(image.shape[0], y + anchor.height + 3)
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
                max(0, y - anchor.height // 2) : y + anchor.height // 2 + 1,
                max(0, x - anchor.width // 2) : x + anchor.width // 2 + 1,
            ] = -1
        return found

    def detect(self, image: Image) -> Observation:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        candidates: list[Detection] = []
        color_index = None
        floor = max(0.5, self.config.confidence - 0.15)
        for template in self.templates:
            height, width = template.gray.shape
            if height > image.shape[0] or width > image.shape[1]:
                continue
            if template.signature is not None:
                if color_index is None:
                    color_index = self._color_index(image)
                candidates.extend(
                    self._sprite_candidates(image, gray, template, floor, color_index)
                )
                continue
            if template.anchor is not None:
                candidates.extend(self._anchor_candidates(image, gray, template, floor))
                continue
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
        kept: list[Detection] = []
        for candidate in sorted(candidates, key=lambda item: item.confidence, reverse=True):
            if not any(
                item.kind == candidate.kind and item.box.iou(candidate.box) > 0.25 for item in kept
            ):
                kept.append(candidate)
        players = [item for item in kept if item.kind == "player"]
        failures = []
        player = players[0] if players and players[0].confidence >= self.config.confidence else None
        if player and len(players) > 1:
            if player.confidence - players[1].confidence < self.config.player_margin:
                player = None
                failures.append("Ambiguous player: multiple similar matches")
        if player is None:
            failures.append("Player detection missing or below confidence threshold")
        monsters = [
            item
            for item in kept
            if item.kind == "monster" and (not player or item.box.iou(player.box) < 0.2)
        ]
        if not monsters:
            failures.append("No visible monster template matches")
        elif not any(item.confidence >= self.config.confidence for item in monsters):
            failures.append("Monster matches below confidence threshold")
        shift, response = self.camera.update(image)
        return Observation(player, monsters, failures, shift, response)


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
    cv2.rectangle(output, (0, 0), (image.shape[1], 46), (20, 27, 24), -1)
    cv2.putText(output, state, (8, 17), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 240, 200), 1)
    cv2.putText(output, reason[:110], (8, 36), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (220, 220, 240), 1)
    return output
