from pathlib import Path

import cv2

from maplebot import perception
from maplebot.config import PerceptionConfig
from maplebot.perception import TemplateDetector


def test_subset_search_reuses_only_identical_pixels_and_evicts_removed_templates(monkeypatch):
    root = Path(__file__).parent / 'fixtures' / 'vine-nametag'
    detector = TemplateDetector(root / 'ambiguity', PerceptionConfig())
    image = cv2.imread(str(root / 'occluded.png'))
    a, b = detector.templates[:2], detector.templates[2:]
    calls = []
    original = perception._native_masked_match

    def counted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(perception, '_native_masked_match', counted)

    def search(templates, pixels=image):
        return detector._candidates(pixels, cv2.cvtColor(pixels, cv2.COLOR_BGR2GRAY),
                                    templates, .7)

    try:
        expected = search(a)
        assert expected and calls
        search(b)
        calls.clear()
        assert search(a) == expected
        assert not calls
        changed = image.copy()
        changed[50:85, 155:195] = 0
        cached = search(a, changed)
        assert calls
        detector.masked_cache.clear()
        assert search(a, changed) == cached
        detector.templates = b
        search(b)
        assert not set(map(id, a)) & detector.masked_cache.keys()
    finally:
        detector.pool.shutdown()
        detector.map_filter.close()


def test_retired_learned_and_dark_templates_do_not_accumulate():
    root = Path(__file__).parent / 'fixtures' / 'vine-nametag'
    detector = TemplateDetector(root / 'ambiguity', PerceptionConfig())
    image = cv2.imread(str(root / 'occluded.png'))
    try:
        a, b = detector.templates[:2], detector.templates[2:]
        detector.templates = a
        detector.fresh.append(b)
        detector._candidates(image, cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), b, .7)
        detector.dark_templates[id(b[0])] = b[1]
        detector.fresh.clear()
        detector._candidates(image, cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), a, .7)
        assert set(detector.masked_cache) <= set(map(id, a))
    finally:
        detector.pool.shutdown()
        detector.map_filter.close()
