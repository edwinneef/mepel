"""Create geometry from a confidently recognized frame, without gameplay input."""

import uuid

from .minimap_reader import describe
from .profiles import SCHEMA_VERSION, AreaStore
from .public_map import build_area, cached


def create_area(store: AreaStore, image, recognition) -> str | None:
    map_id = recognition.map_id
    if map_id is None or recognition.error or recognition.source_error or recognition.held:
        return None
    # Never fetch during tracking, or overwrite a previously saved map.
    if not (store.directory / "public" / f"{map_id}.json").is_file():
        return None
    with store.lock:
        for item in store.list()["areas"]:
            profile = store.load(item["id"])["profile"]
            if profile.get("public_map", {}).get("id") == map_id:
                return None
        source, digest = cached(store.directory, map_id)
        view = {"id": uuid.uuid4().hex, "name": "Captured view",
                "width": image.shape[1], "height": image.shape[0],
                "origin": {"x": 0, "y": 0}, "scale": 1,
                "image": "0" * 64, "minimap": describe(image)}
        profile = {"schema_version": SCHEMA_VERSION, "id": uuid.uuid4().hex,
                   "revision": 0, "name": recognition.title, "views": [view]}
        candidate = build_area(profile, image, source, digest, automatic=True)
        # Only a successful alignment may persist the reference frame.
        captured = store.capture_view(image)
        candidate["views"] = [captured]
        candidate["automatic_alignment"].update(view_id=captured["id"],
                                                view_image=captured["image"])
        return store.save(candidate)["profile"]["id"]
