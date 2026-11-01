"""Reload navigation code while Bot is Off; never starts gameplay or acknowledges alarms."""

import argparse
import json

from tools.navigation_check import Debugger


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://127.0.0.1:8765")
    args = parser.parse_args()
    print(json.dumps(Debugger(args.base).command("nav_reload_code")))


if __name__ == "__main__":
    main()
