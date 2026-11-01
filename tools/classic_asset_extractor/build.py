"""Build the separate GPL extractor from a pinned local checkout and offline NuGet cache."""

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

COMMIT = "04570d43cd90e1b42f613226dd0be22ce58abd1c"


def run(command, **kwargs):
    return subprocess.run(command, check=True, capture_output=True, text=True,
                          timeout=120, **kwargs).stdout.strip()


def build(root, cache, output):
    root, cache, output = (p.resolve() for p in (root, cache, output))
    if output.exists():
        raise ValueError("Use a new parser output directory")
    if run(["git", "-C", str(root), "rev-parse", "HEAD"]) != COMMIT:
        raise ValueError("MapleLib commit mismatch")
    if run(["git", "-C", str(root), "status", "--porcelain", "--untracked-files=normal"]):
        raise ValueError("MapleLib checkout must be clean")
    if not run(["dotnet", "--version"]).startswith("10."):
        raise ValueError(".NET SDK 10 required")
    licenses = {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                for name in ("LICENSE", "spine-runtimes-2.1.25/LICENSE")}
    if not cache.is_dir():
        raise ValueError("An existing offline NuGet cache is required")
    project = Path(__file__).with_name("ClassicAssetExtractor.csproj")
    props = [f"-p:MapleLibRoot={root}", "-p:PublishAot=false",
             "-p:UseSharedCompilation=false", "-p:NuGetAudit=false"]
    env = {**os.environ, "DOTNET_CLI_TELEMETRY_OPTOUT": "1",
           "MSBUILDDISABLENODEREUSE": "1"}
    # The only restore source is an empty local directory; missing packages fail offline.
    with tempfile.TemporaryDirectory(prefix="classic-build-") as temporary:
        run(["dotnet", "restore", str(project), "--source", temporary,
             "--packages", str(cache), *props], env=env)
        run(["dotnet", "build", str(project), "--no-restore", "-c", "Release",
             "--output", str(output), "-v", "quiet", "-nodeReuse:false", *props], env=env)
    if run(["git", "-C", str(root), "status", "--porcelain", "--untracked-files=normal"]):
        raise ValueError("Parser source changed during build")
    receipt = {"schema": 1, "commit": COMMIT, "licenses": licenses,
               "usage": "Local diagnostic only; dependencies not redistributed",
               "extractor_sources": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                     for p in (project, project.with_name("Program.cs"))},
               "files": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in sorted(output.iterdir()) if p.suffix in (".dll", ".json")}}
    (output / "parser-receipt.json").write_text(json.dumps(receipt, sort_keys=True, indent=2)
                                               + "\n", encoding="utf-8")
    return output / "ClassicAssetExtractor.dll"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--maplelib-root", type=Path, required=True)
    parser.add_argument("--package-cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(build(args.maplelib_root, args.package_cache, args.output))
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        detail = getattr(error, "stdout", "") or getattr(error, "stderr", "") or str(error)
        parser.exit(1, f"Offline build refused: {detail}\n")
