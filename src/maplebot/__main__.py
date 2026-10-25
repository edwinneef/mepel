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
    args = parser.parse_args()
    config = Config.load(args.config)
    if args.command == "catalog":
        from .catalog import (
            STARTER_IDS,
            import_catalog,
            import_map_catalog,
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
        if args.max_level is not None:
            result["map_catalog"] = import_map_catalog(Path(config.capture.data_dir) / "templates")
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
    server = serve(app, config.debugger.port, on_restart=restart_requested.set)
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
