"""Build the Southperry scenery reader using only an existing pinned checkout/cache."""

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path

from tools.classic_asset_extractor.build import COMMIT, run


def build(root, cache, output):
    root, cache, output = (p.resolve() for p in (root, cache, output))
    if output.exists() or not cache.is_dir():
        raise ValueError("Use a new output and an existing offline package cache")
    if run(["git", "-C", str(root), "rev-parse", "HEAD"]) != COMMIT:
        raise ValueError("MapleLib commit mismatch")
    if run(["git", "-C", str(root), "status", "--porcelain"]):
        raise ValueError("MapleLib must be clean")
    if not run(["dotnet", "--version"]).startswith("10."):
        raise ValueError(".NET SDK 10 required")
    project = Path(__file__).with_name("SouthperryScenery.csproj")
    props = [f"-p:MapleLibRoot={root}", "-p:PublishAot=false",
             "-p:UseSharedCompilation=false", "-p:NuGetAudit=false"]
    env = {**os.environ, "DOTNET_CLI_TELEMETRY_OPTOUT": "1", "MSBUILDDISABLENODEREUSE": "1"}
    with tempfile.TemporaryDirectory(prefix="southperry-offline-feed-") as empty:
        run(["dotnet", "restore", str(project), "--source", empty,
             "--packages", str(cache), *props], env=env)
        run(["dotnet", "build", str(project), "--no-restore", "-c", "Release", "--output",
             str(output), "-v", "quiet", "-nodeReuse:false", *props], env=env)
    if run(["git", "-C", str(root), "status", "--porcelain"]):
        raise ValueError("MapleLib changed during build")
    def sha(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    receipt = {"schema": 1, "commit": COMMIT, "no_downloads": True,
               "sources": {p.name: sha(p) for p in
                           (project, project.with_name("Program.cs"), Path(__file__))},
               "licenses": {name: sha(root / name) for name in
                            ("LICENSE", "spine-runtimes-2.1.25/LICENSE")},
               "files": {p.name: sha(p) for p in output.iterdir() if p.suffix in (".dll", ".json")}}
    (output / "parser-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n",
                                               encoding="utf-8")
    return output / "SouthperryScenery.dll"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in ("maplelib-root", "package-cache", "output"):
        parser.add_argument("--" + argument, required=True, type=Path)
    args = parser.parse_args()
    print(build(args.maplelib_root, args.package_cache, args.output))
