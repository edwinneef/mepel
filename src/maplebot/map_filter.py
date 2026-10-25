"""Offline map-title recognition narrows sprite searches; unknown maps use all references."""

import asyncio
import json
import re
from concurrent.futures import ThreadPoolExecutor
from difflib import SequenceMatcher
from pathlib import Path

import cv2
import numpy as np


def normalize(text: str) -> str:
    return "".join(character for character in text.casefold() if character.isalnum())


def read_title(image: np.ndarray) -> str:
    from winrt.windows.globalization import Language
    from winrt.windows.graphics.imaging import BitmapAlphaMode, BitmapPixelFormat, SoftwareBitmap
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.storage.streams import DataWriter

    async def recognize() -> str:
        engine = OcrEngine.try_create_from_language(Language("en-US"))
        if engine is None:
            raise RuntimeError("Windows English OCR is unavailable")
        writer = DataWriter()
        writer.write_bytes(cv2.cvtColor(image, cv2.COLOR_BGR2BGRA).tobytes())
        bitmap = SoftwareBitmap.create_copy_from_buffer(
            writer.detach_buffer(),
            BitmapPixelFormat.BGRA8,
            image.shape[1],
            image.shape[0],
            BitmapAlphaMode.IGNORE,
        )
        try:
            result = await engine.recognize_async(bitmap)
            return " ".join(line.text for line in result.lines)
        finally:
            bitmap.close()
            writer.close()

    return asyncio.run(recognize())


class MapFilter:
    def __init__(self, directory: Path, entries: list[dict]):
        path = directory / "catalog" / "maps.json"
        self.profiles = json.loads(path.read_text("utf-8")) if path.exists() else []
        self.names = {entry["id"]: entry["name"] for entry in entries}
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="map-title")
        self.pending = None
        self.previous = None
        self.allowed = None
        self.title = None
        self.error = None
        self.taught: tuple[str | None, set[str]] | None = None
        self.held = False

    def match(self, text: str) -> tuple[str | None, set[str] | None]:
        text = normalize(text)
        matches = [
            profile
            for profile in self.profiles
            if normalize(profile["streetName"])
            and normalize(profile["name"])
            and normalize(profile["streetName"] + profile["name"]) in text
        ]
        if not matches:
            ranked = {}
            for profile in self.profiles:
                street, name = normalize(profile["streetName"]), normalize(profile["name"])
                if not street or street not in text or len(name) < 5:
                    continue
                observed = text.split(street, 1)[1]
                if re.findall(r"\d+", observed) != re.findall(r"\d+", name):
                    continue
                score = SequenceMatcher(None, observed, name).ratio()
                ranked[street + name] = max(score, ranked.get(street + name, 0))
            candidates = sorted(ranked, key=ranked.get, reverse=True)
            if candidates:
                best = candidates[0]
                runner_up = ranked[candidates[1]] if len(candidates) > 1 else 0
                if ranked[best] >= 0.92 and ranked[best] - runner_up >= 0.05:
                    matches = [
                        p for p in self.profiles if normalize(p["streetName"] + p["name"]) == best
                    ]
        if not matches:
            return None, None
        # Identically named maps share a union, so ambiguous titles cannot omit their mobs.
        longest = max(len(normalize(p["streetName"] + p["name"])) for p in matches)
        matches = [p for p in matches if len(normalize(p["streetName"] + p["name"])) == longest]
        return matches[0]["name"], {
            self.names[mob]
            for profile in matches
            for mob in profile["monsters"]
            if mob in self.names
        }

    def select(self, image: np.ndarray, taught_map: bool = False) -> set[str] | None:
        """Monster names for the recognized map title, or None for the full catalog.

        With `taught_map`, the taught area's minimap picture confirms the map, so an
        unreadable title (collapsed minimap) keeps the set recognized on that map.
        """
        allowed = self._select(image)
        self.held = allowed is None and taught_map and self.taught is not None
        if not taught_map:
            self.taught = None
        elif allowed is not None:
            self.taught = (self.title, allowed)
        if self.held:
            assert self.taught is not None
            return self.taught[1]
        return allowed

    def _select(self, image: np.ndarray) -> set[str] | None:
        if not self.profiles or self.error:
            return None
        # Expanded minimap titles are white; collapsed title bars contain dark text.
        crop = image[:64, :310]
        expanded = bool(np.any(np.min(crop[25:62, :275], axis=2) > 180))
        if expanded:
            mask = np.min(crop[25:62, :275], axis=2) > 180
            title = np.repeat((np.uint8(~mask) * 255)[:, :, None], 3, axis=2)
        else:
            title = crop[:19].copy()
        changed = self.previous is None or (
            title.shape != self.previous.shape
            or np.count_nonzero(cv2.absdiff(title, self.previous) > 12) > title.size * 0.01
        )
        if changed:
            self.allowed, self.title = None, None
        if self.pending is not None and self.pending.done():
            try:
                text = self.pending.result()
                if not changed:
                    self.title, self.allowed = self.match(text)
            except Exception as error:
                self.error = str(error)
            self.pending = None
        if changed and self.pending is None and not self.error:
            self.previous = title.copy()
            if expanded:
                title = cv2.copyMakeBorder(
                    title, 8, 8, 8, 8, cv2.BORDER_CONSTANT, value=(255, 255, 255)
                )
                title = cv2.resize(title, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
            else:
                title = cv2.resize(title, None, fx=3, fy=3, interpolation=cv2.INTER_NEAREST)
            self.pending = self.pool.submit(read_title, title)
        return self.allowed

    def close(self) -> None:
        self.pool.shutdown(wait=False, cancel_futures=True)
