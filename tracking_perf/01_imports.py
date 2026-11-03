# VALIDATION / MEASUREMENTS
# 153 isolated pytest checks passed in the editing environment. These are NOT
# the application's test suite: missing Rect/config/lifecycle dependencies were
# stubbed for isolated method tests. No gameplay or keyboard input was run.
# Python 3.12 syntax checked; execution tests used Python 3.13.5 on Linux,
# OpenCV 4.13.0 and NumPy 2.3.5. Windows/MSS capture was not exercised live.
# Tests cover native score maps and candidate locations, cache reuse/invalidation,
# low-contrast/weighted masks, sprite scoring, exact coarse-ROI boundaries,
# refresh backoff, image ownership, and AST checks of unchanged safety methods.
# Synthetic benchmarks use ONE OpenCV thread in BOTH versions and four template
# workers. This patch does not change process-global OpenCV thread settings.
# BGRA to owned contiguous BGR 1280x720:
#   median 4.074 -> 0.083 ms (49.08x); p95 4.341 -> 0.103 ms.
# BGRA to owned contiguous BGR 2560x1440:
#   median 17.523 -> 0.676 ms (25.92x); p95 20.112 -> 1.040 ms.
# One 48x64 anchored template, 350x240 ROI, uncached proposals:
#   median 31.691 -> 10.488 ms (3.02x); p95 35.247 -> 11.299 ms.
# Eight player templates, moving synthetic frames, 350x240 player ROI, four workers:
#   median 83.507 -> 36.914 ms (2.26x); p95 104.724 -> 42.966 ms.
# These timings are not full-pipeline FPS or a prediction for another machine.
# Benchmark with the real recordings/templates and inspect _pace before claiming
# a live-frame-rate increase. Keep both encoder frame copies unless its missing
# ownership contract is reviewed. Do not run or send gameplay input for validation.
#
# OPTIMIZED REFERENCE SNAPSHOT -- merge each group into its original module.
# This is not an executable module. The only added import is cv2 in capture.py.
# Apply 02 as capture.py; merge the Application methods from 03 and the
# helpers/classes/methods from 04 into the existing modules. Do not replace
# runtime.py or perception.py wholesale: their omitted code is still required.
#
# Do not add cv2.setNumThreads() inside worker methods: it is process-global.
# Thread-count experiments belong in application startup, before workers exist.
# No changes to keyboard output, confidence thresholds, full-scan cadence,
# camera/identity logic, encoder ownership, or freshness deadlines are required.


# ===== src/maplebot/capture.py =====
import json
import shutil
import time
from dataclasses import asdict, dataclass
from pathlib import Path
import cv2
import mss
import numpy as np
from numpy.typing import NDArray
from .geometry import Rect
from .windows import Window, Windows

# ===== src/maplebot/runtime.py =====
import base64
import hashlib
import json
import math
import queue
import re
import threading
import time
import uuid
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import Any
import cv2
import numpy as np
from . import key_settings
from .alarm import AlarmManager
from .attack_ranges import RangeStore, range_options, range_profile
from .autopotter import BarReading, PotionMonitor
from .capture import Calibration, Capture, CaptureMovedError, Image
from .combat_evidence import CombatEvidence
from .combat_readiness import summarize
from .config import Config
from .contracts import (
    FRESH_FRAME_COMMANDS,
    FRESH_FRAME_SECONDS,
    CommandContext,
    catalog_warning,
    readiness,
)
from .decision import Action, Agent, Decision, PolicyInput
from .display_loop import DisplayLoop, DisplaySource
from .farming import CHECKPOINT_STOP, Farming
from .farming_routes import (
    FarmingRouteStore,
    compile_route,
    preview_graph,
    restrict_graph,
    route_options,
)
from .frame_encoder import FrameEncoder, FramePacket
from .geometry import Rect
from .hotkeys import HotkeyCounter
from .keyboard import (
    KEYS,
    DisabledInput,
    InputBackend,
    InputObservation,
    KeyboardController,
    Win32Input,
)
from .live_position import STALE_SECONDS, LivePosition, detect_area
from .navigation_runtime import NavigationRuntime
from .overlay_session import START_COMMANDS
from .perception import NameTag, TemplateDetector, annotate, nametag_parts
from .pose_collection import PoseCollection
from .potion_evidence import PotionEvidence, PotionFrame
from .preview_stream import PreviewSource, PreviewStream
from .probe_store import ProbeStore
from .profiles import AreaStore
from .reacquisition import Reacquisition
from .recorder import SessionRecorder
from .rotation import CircuitRotation, Rotation, routable, visible_by_surface
from .scheduler import SUSTAIN, Arbiter
from .windows import Window, Windows

# ===== src/maplebot/perception.py =====
import hashlib
import json
import math
import os
import time
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor, wait
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
from .reacquisition import CHAIN_RADIUS, CHAIN_SPEED, RECOVERY_SECONDS, ConfirmedSprites
