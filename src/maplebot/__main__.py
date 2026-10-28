import argparse
import json
from pathlib import Path

from .config import Config


def main() -> None:
    parser = argparse.ArgumentParser(description="Screenshot-only external MapleStory agent")
    parser.add_argument("--config", type=Path, default=Path("config.toml"))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="Report Python/display/window environment; sends no input")
    debug = sub.add_parser(
        "debug", help="Start capture and calibration debugger; input disabled by default"
    )
    debug.add_argument(
        "--capture-only",
        action="store_true",
        help="Lock out all keyboard output for this session, including control probes",
    )
    replay = sub.add_parser("replay", help="Offline decisions and benchmarks; never sends input")
    replay.add_argument("frames", type=Path)
    replay.add_argument("--templates", type=Path, default=Path("data/templates"))
    replay.add_argument("--output", type=Path, default=Path("artifacts/replay"))
    replay.add_argument("--labels", type=Path)
    replay.add_argument("--annotated", action="store_true")
    replay.add_argument("--autopotter", type=Path, help="Saved HUD calibration for potion preview")
    replay.add_argument(
        "--policy-only",
        action="store_true",
        help="Replay logged policy inputs only; never loads screenshots, templates, or input",
    )
    catalog = sub.add_parser("catalog", help="Import public enemy sprites for offline detection")
    selection = catalog.add_mutually_exclusive_group()
    selection.add_argument(
        "--ids",
        nargs="+",
        type=int,
        help="Monster IDs; defaults to 12 classic ground-monster species",
    )
    selection.add_argument(
        "--max-level", type=int, help="Import all non-boss monster IDs through this level"
    )
    spawn = sub.add_parser("spawn-import", help="Install a reviewed local spawn dataset")
    spawn.add_argument("source", type=Path)
    spawn.add_argument("--dry-run", action="store_true")
    osms = sub.add_parser("osms-import", help="Import a pinned Classic population dataset")
    from .osms_import import VERIFIED_COMMIT

    osms.add_argument("--commit", default=VERIFIED_COMMIT)
    osms.add_argument("--dry-run", action="store_true")
    sprites = sub.add_parser("osms-sprites", help="Add missing sprites for selected OSMS maps")
    sprites.add_argument("--dry-run", action="store_true")
    sub.add_parser("legacy-map-import", help="Explicitly import legacy Dream map populations")
    import_map = sub.add_parser(
        "import-map", help="Replace a saved area's geometry with its public map (engine stopped)"
    )
    import_map.add_argument("area", help="Saved area ID or exact name")
    import_map.add_argument("--map-id", type=int, help="Public map ID when the name does not match")
    import_map.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    config = Config.load(args.config)
    if args.command == "import-map":
        from .map_import import engine_running
        from .map_import import import_map as run_import
        from .profiles import AreaStore

        if not args.dry_run and engine_running(config.debugger.port):
            raise SystemExit("Stop the engine before importing a map; it holds the saved area")
        root = Path(config.capture.data_dir)
        result = run_import(AreaStore(root / "areas"), args.area,
                            root / "templates" / "catalog" / "maps.json",
                            map_id=args.map_id, dry_run=args.dry_run)
        print(json.dumps(result, indent=2))
        return
    if args.command == "osms-sprites":
        from .osms_sprites import import_sprites

        root = Path(config.capture.data_dir)
        source, revision = config.perception.spawn_source, config.perception.spawn_revision
        if source != "osms-classic" or not revision.isalnum():
            raise ValueError("Select a pinned OSMS dataset first")
        print(json.dumps(import_sprites(
            root / "templates", root / "spawn-metadata" / source / f"{revision}.json",
            dry_run=args.dry_run
        ), indent=2))
        return
    if args.command == "osms-import":
        from .osms_import import import_osms

        root = Path(config.capture.data_dir)
        manifest = root / "templates/catalog/manifest.json"
        entries = json.loads(manifest.read_text("utf-8"))["entries"] if manifest.exists() else []
        print(json.dumps(import_osms(
            root / "spawn-metadata", entries, args.commit, dry_run=args.dry_run
        ), indent=2))
        return
    if args.command == "spawn-import":
        from .spawn_metadata import import_dataset

        print(json.dumps(import_dataset(
            Path(config.capture.data_dir) / "spawn-metadata", args.source, dry_run=args.dry_run
        ), indent=2))
        return
    if args.command == "legacy-map-import":
        from .catalog import import_map_catalog

        print(json.dumps(import_map_catalog(Path(config.capture.data_dir) / "templates"), indent=2))
        return
    if args.command == "catalog":
        from .catalog import (
            STARTER_IDS,
            import_catalog,
            monster_ids_through_level,
        )

        ids = (
            monster_ids_through_level(args.max_level)
            if args.max_level is not None
            else args.ids or STARTER_IDS
        )
        result = import_catalog(
            Path(config.capture.data_dir) / "templates",
            ids,
            actions=("stand", "move", "jump", "hit1"),
        )
        print(json.dumps(result, indent=2))
        return
    if args.command == "replay":
        if args.policy_only:
            from .replay import write_policy_diff

            try:
                result = write_policy_diff(args.frames, args.output, config)
            except ValueError as error:
                print(json.dumps({"error": str(error), "input_sent": False}))
                raise SystemExit(1) from error
            print(json.dumps(result, indent=2))
            if result["differences"]:
                raise SystemExit(1)
            return
        from .replay import run_replay

        print(
            json.dumps(
                run_replay(
                    args.frames,
                    args.templates,
                    args.output,
                    config,
                    args.labels,
                    args.annotated,
                    args.autopotter,
                ),
                indent=2,
            )
        )
        return
    if args.command == "doctor":
        import platform

        import cv2
        import mss

        from .windows import Windows

        windows = Windows()
        with mss.MSS() as screen:
            print(
                json.dumps(
                    {
                        "python": platform.python_version(),
                        "os": platform.platform(),
                        "opencv": cv2.__version__,
                        "monitors": screen.monitors,
                        "matching_windows": [
                            window.title
                            for window in windows.list()
                            if config.capture.window_title.casefold() in window.title.casefold()
                        ],
                    },
                    indent=2,
                )
            )
        return
    import os
    import subprocess
    import sys
    import threading

    from .debugger import serve
    from .runtime import Application

    app = Application(config, capture_only=args.capture_only)
    restart_requested = threading.Event()
    server = serve(
        app, config.debugger.port,
        on_restart=restart_requested.set, on_shutdown=app.closed.set,
    )
    app.start()
    input_status = (
        "capture-only: keyboard output locked" if args.capture_only else "gameplay input disabled"
    )
    print(
        f"Debugger: http://127.0.0.1:{config.debugger.port} ({input_status})",
        flush=True,
    )
    try:
        while not restart_requested.is_set() and not app.closed.wait(0.25):
            pass
    except KeyboardInterrupt:
        pass
    finally:
        app.close()
        server.shutdown()
        server.server_close()
    if restart_requested.is_set():
        # os.execv on Windows leaves the old process running and holding the port, so start
        # the replacement ourselves (the socket is already closed) and end this process.
        subprocess.Popen([sys.executable, "-m", "maplebot", *sys.argv[1:]])
        sys.stdout.flush()
        os._exit(0)


if __name__ == "__main__":
    main()
