# src/maplebot/perception.py -- optimized selected pieces, NOT a full replacement.
# Merge the added MaskedPixels class, Template.masked_pixels property and
# _native_masked_match helper as well as the changed methods below.
# Existing source-range labels refer to the ORIGINAL, not the revised line numbers.
#
# Main changes:
# - Sparse native-pixel verification for small binary-masked anchor searches.
#   Coarse proposals, floors, ambiguity checks and full scans are unchanged.
# - Cache immutable per-template mask pixels/reference statistics; bound temporary
#   allocation sizes and avoid a BLAS thread team for small dot products.
# - Reuse byte-identical crop-cache entries without recopying their inputs.
# - Only downsample the needed player area (with a 2px halo for identical edges)
#   when no non-player anchor needs the full coarse frame.
# - Back off failed GrabCut refresh attempts, not only successful refreshes.
# - Add search-detail timings, separate from the existing top-level stage timings.
#
# Template pixel arrays must remain immutable after construction, as already
# required by Template.anchored. Reload/replace creates a new Template.
# Numerical boundary/tie cases use the original OpenCV masked implementation.
# Real recorded-frame parity and live FPS still require the complete project.
# Excluded: CameraTracker, enemy tracking, _uncover, _predict/_learn_motion, _tracking_snapshot,
# TemplateDetector.reload/add/_variants (template loading), annotate(), most of the file's helpers.

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
class MaskedPixels:
    """Immutable preparation shared by native verification and sprite scoring."""

    rows: np.ndarray
    cols: np.ndarray
    colors: np.ndarray
    centered_gray: np.ndarray
    gray_norm: float
    color_energy: float


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

    @cached_property
    def masked_pixels(self) -> MaskedPixels:
        """Prepare once per immutable template, instead of per candidate/frame."""
        anchor = self.anchor
        assert anchor is not None and self.mask is not None
        rows, cols = np.nonzero(self.mask != 0)
        colors = self.image[rows + anchor.y, cols + anchor.x].astype(np.float32)
        gray = self.gray[rows + anchor.y, cols + anchor.x].astype(np.float32)
        centered = gray - gray.mean() if gray.size else gray
        return MaskedPixels(rows, cols, colors, centered,
                            float(np.linalg.norm(centered)), float((colors * colors).sum()))


# Formula reference: https://docs.opencv.org/4.13.0/df/dfb/group__imgproc__object.html
def _native_masked_match(crop: Image, template: Template, method: int) -> Image:
    """The binary-mask OpenCV formula at the few offsets in a native proposal.

    Large result maps, weighted masks and low-contrast references retain the
    original OpenCV implementation. np.einsum(..., optimize=False) keeps these
    tiny reductions out of multithreaded BLAS. This helper never mutates a crop.
    """
    anchor = template.anchor
    assert anchor is not None and template.mask is not None
    reference, reference_gray, _ = template.anchored
    output_h = crop.shape[0] - anchor.height + 1
    output_w = crop.shape[1] - anchor.width + 1
    native = (template.mask.dtype == np.uint8 and template.mask.ndim == 2
              and output_h > 0 and output_w > 0 and output_h * output_w <= 256
              and method in (cv2.TM_CCOEFF_NORMED, cv2.TM_SQDIFF_NORMED))
    ref = reference_gray if crop.ndim == 2 else reference
    if not native:
        return cv2.matchTemplate(crop, ref, method, mask=template.mask)
    data = template.masked_pixels
    if (not len(data.rows) or data.color_energy <= 0
            or data.gray_norm ** 2 < 64 * len(data.rows)):
        # Near-flat reference: retain OpenCV's normalization/degenerate behavior.
        return cv2.matchTemplate(crop, ref, method, mask=template.mask)
    yy, xx = np.indices((output_h, output_w))
    yy, xx = yy.ravel(), xx.ravel()
    result = np.empty(len(xx), dtype=np.float32)
    # At most ~1 MiB of grayscale samples / ~3 MiB of color samples per chunk.
    chunk = max(1, min(256, 262_144 // len(data.rows)))
    for start in range(0, len(xx), chunk):
        stop = min(start + chunk, len(xx))
        py = yy[start:stop, None] + data.rows
        px = xx[start:stop, None] + data.cols
        observed = crop[py, px].astype(np.float32)
        if method == cv2.TM_CCOEFF_NORMED:
            observed -= observed.mean(axis=1, keepdims=True)
            numerator = np.einsum('ij,j->i', observed, data.centered_gray, optimize=False)
            variance_sum = np.einsum('ij,ij->i', observed, observed, optimize=False)
            if np.any((variance_sum > 0) & (variance_sum < 64 * len(data.rows))):
                return cv2.matchTemplate(crop, reference_gray, method, mask=template.mask)
            denominator = data.gray_norm * np.sqrt(variance_sum)
            # Flat observed pixels remain NaN; the caller converts them to -1.
            values = np.full(stop - start, np.nan, dtype=np.float32)
            np.divide(numerator, denominator, out=values, where=denominator > 0)
        else:
            energy = np.einsum('ijk,ijk->i', observed, observed, optimize=False)
            difference = observed - data.colors
            distance = np.einsum('ijk,ijk->i', difference, difference, optimize=False)
            denominator = np.sqrt(data.color_energy * energy)
            values = np.full(stop - start, np.inf, dtype=np.float32)
            np.divide(distance, denominator, out=values, where=denominator > 0)
        result[start:stop] = values
    return result.reshape(output_h, output_w)

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
    # Operator-entered in-game name, shown instead of the file id. Not used for matching.
    label: str = ""

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

class TemplateDetector:  # (__init__ and other methods omitted)

    # ---- detect (perception.py:1101-1190) ----
    def detect(self, image: Image, now: float | None = None, *,
               monsters: bool = True) -> Observation:
        """monsters=False searches only the player, for work that never targets an enemy."""
        now = time.monotonic() if now is None else now
        began = time.perf_counter()
        self.player_stage_ms = {}
        # Camera motion only needs the frame, so it runs beside recognition.
        pending = self.pending_camera
        if pending is not None and pending[0] is image:
            self.pending_camera, camera = None, pending[1]
        else:
            self._settle_camera()
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

    # ---- _observe (perception.py:1498-1557) ----
    def _observe(
        self, image: Image, now: float, templates: list[Template], floor: float
    ) -> tuple[Detection | None, list[Detection], list[str], float]:
        # These are cumulative wall times if this frame searches multiple ROIs.
        details = getattr(self, "player_stage_ms", None)
        mark = time.perf_counter()

        def stage(name: str) -> None:
            nonlocal mark
            current = time.perf_counter()
            if details is not None:
                details[name] = details.get(name, 0.0) + (current - mark) * 1000
            mark = current

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        self._set_occluders(image.shape[:2], self.track[0] if self.track else None,
                            self.origin)
        stage("gray_occluders_ms")
        # Name tags match in the pool while the sprite templates are searched.
        searches = self._nametag_search(gray)
        tag_area = self._tag_first_area(gray, searches, now)
        if tag_area is not None:
            self.player_area = tag_area
        stage("tag_first_wait_ms")
        candidates = self._candidates(image, gray, templates, floor)
        stage("templates_ms")
        kept = self._suppress(candidates)
        players = [item for item in kept if item.kind == "player"]
        tags = self._nametag_candidates(gray, searches)
        stage("tags_finish_ms")
        if (not any(p.confidence >= self.config.confidence for p in players)
                and not any(m.confidence >= self.config.nametag_confidence for m, _ in tags)):
            players = self._suppress(players + self._dark_player_candidates(image, gray, now))
        stage("dark_fallback_ms")
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
        stage("resolve_fresh_follow_ms")
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
        stage("uncover_ms")
        return player, monsters, failures, tag_confidence

    # ---- _observe_in (perception.py:1446-1468) ----
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

    # ---- _observe_full (perception.py:1470-1496) ----
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

    # ---- _observe_window (perception.py:1329-1369) ----
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

    # ---- _window (perception.py:1303-1318) ----
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

    # ---- _player_area (perception.py:1321-1327) ----
    @staticmethod
    def _player_area(box: Rect, image: Image) -> tuple[int, int, int, int]:
        """The 350 x 240 movement window around the track, at even offsets inside the image."""
        width, height = min(350, image.shape[1]), min(240, image.shape[0])
        cx, cy = box.center
        x = min(max(0, round(cx - width / 2)), image.shape[1] - width) & ~1
        y = min(max(0, round(cy - height / 2)), image.shape[0] - height) & ~1
        return x, y, width, height

    # ---- _scan_tile (perception.py:1387-1444) ----
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

    # ---- _candidates (perception.py:865-925) ----
    def _candidates(
        self, image: Image, gray: Image, templates: list[Template], floor: float
    ) -> list[Detection]:
        usable = [
            template for template in templates
            if template.gray.shape[0] <= image.shape[0] and template.gray.shape[1] <= image.shape[1]
        ]
        # A fallback search uses only learned poses; it must not evict the taught
        # poses needed on the next frame. Retain only currently owned templates,
        # their live dark variants, and this call's temporary templates. Each entry
        # still holds only its latest search's bounded proposal crops.
        live_ids = {id(t) for t in self.templates}
        live_ids.update(id(t) for group in self.fresh for t in group)
        active_ids = live_ids | {id(t) for t in usable}
        active_ids.update(id(t) for source, t in self.dark_templates.items()
                          if source in live_ids)
        self.masked_cache = {key: value for key, value in self.masked_cache.items()
                             if key in active_ids}
        color_index = (
            self._color_index(image)
            if any(template.signature is not None for template in usable) else None
        )

        area = self.player_area
        anchored = [t for t in usable if t.anchor is not None and t.signature is None]
        coarse = player_coarse = None
        if anchored:
            if (area is not None and all(t.kind == "player" for t in anchored)
                    and not (area[0] & 1 or area[1] & 1)):
                x, y, w, h = area
                # pyrDown has a 5x5 footprint. The halo preserves the full-frame
                # result, including the real frame boundary's reflection rule.
                left, top = max(0, x - 2), max(0, y - 2)
                right, bottom = min(gray.shape[1], x + w + 2), min(gray.shape[0], y + h + 2)
                halo = cv2.pyrDown(gray[top:bottom, left:right])
                player_coarse = halo[(y - top) // 2 : (y + h + 1) // 2 - top // 2,
                                     (x - left) // 2 : (x + w + 1) // 2 - left // 2]
            else:
                coarse = cv2.pyrDown(gray)
                if area is not None:
                    x, y, w, h = area
                    player_coarse = coarse[y // 2 : (y + h + 1) // 2,
                                           x // 2 : (x + w + 1) // 2]
        # Prewarm immutable preparation on the owner thread, before parallel jobs.
        for template in usable:
            if (template.anchor is not None and template.mask is not None
                    and template.mask.ndim == 2):
                template.masked_pixels

        def search(template: Template) -> list[Detection]:
            if area is None or template.kind != "player":
                return self._template_candidates(image, gray, template, floor, color_index, coarse)
            # The tracked player is near the window centre. Even offsets keep the coarse
            # slice identical to the whole window's proposals inside the area.
            x, y, w, h = area
            found = self._template_candidates(
                image[y : y + h, x : x + w], gray[y : y + h, x : x + w], template, floor,
                color_index, player_coarse)
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

    # ---- _anchor_candidates (perception.py:778-863) ----
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
                # Reuse immutable stored inputs/results, not three new copies.
                current[key] = saved
                result = saved[1]
            else:
                result = _native_masked_match(crop, template, method)
                current[key] = (crop.copy(), result)
            # Structure is patched in-place below; color is only read by 1 - result.
            return result.copy() if method == cv2.TM_CCOEFF_NORMED else result
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
            if structure is not None:
                bound = COLOR_WEIGHT_CAP + 0.4 * cv2.minMaxLoc(structure)[1]
                if abs(bound - floor) <= 5e-5:
                    structure = cv2.matchTemplate(
                        gray[top:bottom, left:right], reference_gray,
                        cv2.TM_CCOEFF_NORMED, mask=template.mask)
                    cv2.patchNaNs(structure, -1)
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
                # Different reductions can differ in the last float32 bits. Use
                # the original implementation for a borderline decision or tie.
                near_peak = np.count_nonzero(np.abs(score - confidence) <= 5e-5)
                if (abs(confidence - floor) <= 5e-5
                        or abs(confidence - self.config.confidence) <= 5e-5
                        or (confidence >= floor and near_peak > 1)):
                    native_gray = cv2.matchTemplate(
                        gray[top:bottom, left:right], reference_gray,
                        cv2.TM_CCOEFF_NORMED, mask=template.mask)
                    cv2.patchNaNs(native_gray, -1)
                    native_color = 1 - cv2.matchTemplate(
                        image[top:bottom, left:right], reference,
                        cv2.TM_SQDIFF_NORMED, mask=template.mask)
                    score = np.nan_to_num(0.6 * native_color + 0.4 * native_gray,
                                          copy=False, nan=0, posinf=0, neginf=0)
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

    # ---- _sprite_candidates (perception.py:606-614) ----
    def _sprite_candidates(
        self,
        image: Image,
        gray: Image,
        template: Template,
        floor: float,
        index: tuple[np.ndarray, np.ndarray, np.ndarray],
    ) -> list[Detection]:
        return self._sprite_batch(image, gray, [template], floor, index)[0]

    # ---- _sprite_batch (perception.py:626-731) ----
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

    # ---- _sprite_scores (perception.py:733-776) ----
    def _sprite_scores(self, image: Image, gray: Image, template: Template, floor: float,
                       ys: np.ndarray, xs: np.ndarray) -> list[Detection]:
        """Full-mask confidence at the given sprite positions, best first."""
        anchor = template.anchor
        assert anchor is not None and template.mask is not None
        data = template.masked_pixels
        if not len(xs) or not len(data.rows):
            return []
        reference, centered = data.colors, data.centered_gray
        rows, cols = data.rows + anchor.y, data.cols + anchor.x
        reference_norm, energy = data.gray_norm, data.color_energy
        confidences = np.empty(len(xs), dtype=np.float32)
        # Preserve the original batch/reduction order at confidence boundaries.
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

    # ---- _template_candidates (perception.py:927-958) ----
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

    # ---- _player_anchor (perception.py:533-570) ----
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

    # ---- _sprite_signature (perception.py:573-592) ----
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

    # ---- _dark_player_candidates (perception.py:1559-1596) ----
    def _dark_player_candidates(self, image: Image, gray: Image, now: float) -> list[Detection]:
        """Match the dim damage pose only for a recently name-confirmed appearance."""
        previous = self.confirmed_sprites.last
        if previous is None or now - self.lookalike_at < RECOVERY_SECONDS:
            return []
        identity, box, at = previous
        elapsed = now - at
        if not 0 <= elapsed < RECOVERY_SECONDS:
            return []
        radius = min(TRACK_MAX_RADIUS, CHAIN_RADIUS + CHAIN_SPEED * elapsed)
        box = box.translated(-self.origin[0], -self.origin[1])
        left, top = max(0, int(box.x - radius)), max(0, int(box.y - radius))
        right = min(image.shape[1], math.ceil(box.x + box.width + radius))
        bottom = min(image.shape[0], math.ceil(box.feet + radius))
        if right <= left or bottom <= top:
            return []
        crop, crop_gray = image[top:bottom, left:right], gray[top:bottom, left:right]
        templates = [t for t in self.templates if t.kind == "player"]
        templates += [t for group in self.fresh for t in group]
        active = {id(t) for t in templates}
        for key in set(self.dark_templates) - active:
            self.masked_cache.pop(id(self.dark_templates.pop(key)), None)
        found = []
        for template in templates:
            if (template.anchor is None or template.mask is None
                    or self.confirmed_sprites.names.get(template.name) != identity):
                continue
            dark = self.dark_templates.get(id(template))
            if dark is None:
                pixels = (template.image.astype(np.uint16) // 2).astype(np.uint8)
                dark = replace(template, image=pixels,
                               gray=cv2.cvtColor(pixels, cv2.COLOR_BGR2GRAY), signature=None)
                self.dark_templates[id(template)] = dark
            for candidate in self._anchor_candidates(crop, crop_gray, dark, self.config.confidence):
                candidate = replace(candidate, box=candidate.box.translated(left, top))
                if math.dist(candidate.box.center, box.center) <= radius:
                    found.append(candidate)
        return found

    # ---- _follow (perception.py:1646-1688) ----
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

    # ---- _refresh_sprite (perception.py:1598-1644) ----
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
        # Back off failed segmentations too. Previously an empty fresh deque
        # could cause five GrabCut iterations on EVERY confirmed-tag frame.
        context = (id(self.confirmed_sprites), image.shape, player.template.split(":")[1])
        previous_attempt = getattr(self, "_sprite_refresh_attempt", None)
        if (previous_attempt is not None and previous_attempt[0] == context
                and 0 <= now - previous_attempt[1] < REFRESH_SECONDS):
            return
        self._sprite_refresh_attempt = (context, now)
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

    # ---- _suppress (perception.py:1045-1055) ----
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

    # ---- _resolve (perception.py:1057-1078) ----
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

    # ---- load_nametag (perception.py:480-495) ----
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
            str(meta.get("label", "")),
        )

    # ---- nametag_matches (perception.py:497-518) ----
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

    # ---- body_from_nametag (perception.py:521-524) ----
    @staticmethod
    def body_from_nametag(tag: NameTag, box: Rect) -> Rect:
        width, height = tag.player_size
        feet = box.y + tag.text_top - NAMETAG_FEET_GAP
        return Rect(round(box.x + box.width / 2 - width / 2), feet - height, width, height)

    # ---- search_tags (perception.py:1732-1741) ----
    @property
    def search_tags(self) -> list[NameTag]:
        """Taught tags of the configured character; every tag when none carries its name.

        Tags taught for other characters only cost search time, and a match on one would
        mistake that character for the player.
        """
        name = self.config.player_name.strip().casefold()
        chosen = [tag for tag in self.nametags
                  if name and getattr(tag, "label", "").strip().casefold() == name]
        return chosen or self.nametags

    # ---- _nametag_search (perception.py:1743-1750) ----
    def _nametag_search(self, gray: Image) -> list[Future[list[Detection]]]:
        """Start matching each searched name tag in the pool, in self.search_tags order."""
        floor = max(0.5, self.config.nametag_confidence - 0.15)
        # Remember the pool so results pair with the same tags even if a label changes.
        self.searched_tags = self.search_tags
        if not self.searched_tags:
            return []
        near_white = np.float32(gray >= NAMETAG_TEXT)
        return [self.pool.submit(self.nametag_matches, gray, tag, floor, near_white)
                for tag in self.searched_tags]

    # ---- _nametag_candidates (perception.py:1752-1773) ----
    def _nametag_candidates(
        self, gray: Image, searches: list[Future[list[Detection]]] | None = None
    ) -> list[tuple[Detection, NameTag]]:
        searches = self._nametag_search(gray) if searches is None else searches
        matches = sorted(
            (
                (match, tag)
                for tag, search in zip(self.searched_tags, searches, strict=True)
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

    # ---- _fuse_nametag (perception.py:1775-1856) ----
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

    # ---- _partial_nametag (perception.py:1690-1706) ----
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

    # ---- _tag_first_area (perception.py:1708-1729) ----
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

    # ---- _occluded_tag_score (perception.py:1858-1876) ----
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
