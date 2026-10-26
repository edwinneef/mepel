"""Prepare or restore a review-only teaching merge while the debugger is stopped."""

import argparse
import json
import socket
from pathlib import Path

from teaching_route_diagnosis import diagnose

from maplebot.teaching_merge import prepare, restore


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--areas", type=Path, default=Path("data/areas"))
    parser.add_argument("--area-id", default="98a20c69939d450fb46e5e9342b83734")
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--port", type=int, default=8765)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--apply", action="store_true")
    action.add_argument("--restore", type=Path)
    args = parser.parse_args()
    if args.apply or args.restore:
        try:
            with socket.create_connection(("127.0.0.1", args.port), timeout=1):
                raise SystemExit("Stop the debugger before changing its teaching checkpoint")
        except OSError:
            pass
    if args.restore:
        result = restore(args.restore)
    else:
        diagnosis = diagnose(args.areas, args.area_id)
        if args.apply:
            if not args.backup:
                parser.error("--apply requires a new --backup directory")
            result = prepare(args.areas, args.area_id, diagnosis, args.backup)
        else:
            result = {"dry_run": True, "samples": len(diagnosis["teacher_checkpoint"]["samples"]),
                      "problems": diagnosis["candidate"]["problems"]}
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
