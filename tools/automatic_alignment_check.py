"""Check cached public maps against saved reference views. No capture, input or migration."""

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

from maplebot.map_alignment import align
from maplebot.meowdb import cached_source
from maplebot.profiles import AreaStore, validate_profile
from maplebot.public_map import build_area, cached


def check(directory):
    store = AreaStore(directory)
    results = []
    listing = store.list()
    for area in listing["areas"]:
        profile = store.load(area["id"])["profile"]
        public = profile.get("public_map")
        if not public:
            continue
        row = {"area": area["name"], "id": area["id"]}
        try:
            def missing(_):
                raise ValueError("Public map is not cached; no network access permitted")

            source, digest = (cached_source(directory, public)
                              if public.get("provider") == "meowdb-classic"
                              else cached(directory, public["id"], missing))
            if digest != public["sha256"]:
                raise ValueError("Source digest changed")
            basis = profile.get("automatic_alignment") or profile.get("minimap_calibration")
            view = next(v for v in profile["views"]
                        if v["id"] == (basis["view_id"] if basis else profile["views"][0]["id"]))
            frame = cv2.imdecode(np.frombuffer(store.frame(view["image"]), np.uint8),
                                 cv2.IMREAD_COLOR)
            alignment = align(frame, view["minimap"]["canvas"], source["miniMap"])
            candidate, _ = validate_profile(build_area(profile, frame, source, digest,
                                                       automatic=True))
            row.update(status="aligned", alignment=alignment,
                       platforms=len(candidate["platforms"]))
        except (ValueError, OSError, cv2.error) as error:
            row.update(status="refused", reason=str(error))
        results.append(row)
    return {"input_sent": False, "native_acceptance": False, "profiles_written": False,
            "scope": "Saved reference/minimap registration only; not pixel-accuracy proof",
            "results": results, "load_errors": listing["errors"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--areas", type=Path, default=Path("data/areas"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    target = args.output.resolve()
    protected = (Path(__file__).resolve().parents[1] / "data").resolve()
    if target.is_relative_to(protected) or target.is_relative_to(args.areas.resolve()):
        parser.error("Report must stay outside saved data")
    report = check(args.areas)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, allow_nan=False)
    print(json.dumps({"report": str(target), "aligned": sum(
        r["status"] == "aligned" for r in report["results"]),
        "refused": sum(r["status"] == "refused" for r in report["results"])}))


if __name__ == "__main__":
    main()
