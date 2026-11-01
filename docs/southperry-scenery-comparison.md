# Southperry scenery compared directly with recorded gameplay

Compared three preselected inline assets from the existing hash-pinned artwork copies
against all nine previously copied Southperry screenshots, spanning three recordings.
No game interaction, new capture, installed-file access or download was performed.

Results at original 1:1 pixel scale, using every fully opaque source pixel:

- `obj_housePT.img/house0/basic/0/0`: 75.65–78.60% exact among 174,760 pixels/frame.
- `obj_housePT.img/house0/deco/0/0`: 90.75–92.66% exact among 6,065 pixels/frame.
- `tile_whiteMarble.img/enH0/0`: 100% exact among 1,409 pixels/frame.

All three best matches score worse when displaced by one pixel in any of four
directions, in every frame. The house and decoration independently give identical
screen-minus-exported-map translations: zero-pixel disagreement across all nine frames.
The two templates belong to the same house, so this is a relative camera/placement
consistency check, not independent whole-map accuracy or a held-out-map benchmark.

The source mask is fixed by alpha=255. No mismatch-driven exclusions or source-patch
selection were used. Matching searches the whole screenshot, without consuming logs,
calibration or player positions. Known raw-map placement/origin metadata is used only
after pixel matching to compare the two translations. Transparent/partly transparent
pixels are not scored, and native alpha blending is not established by this test.

Visual inspection of the first full house crop and residual image shows differences
at overlaid stars, roof caps, ropes, a platform, bushes, characters and the mouse cursor.
These regions stay in the score. This explains prominent residual shapes without
claiming every mismatch is explained or that the full sprite matches perfectly.
The platform texture repeats in the scene; a perfect tile match does not identify a
unique world position. Its best matching instance changes in the third recording.

The assets were selected from the previously recorded inline-canvas list and inspected
before scoring: the main house, its star decoration and a stone platform edge. Their
complete PNGs, compressed payloads and origins were extracted from the already copied
`Obj_000.wz` and `Tile_000.wz`. No missing `_Canvas` archive was needed for this check.
Python's separate packed-BGRA4444 decoder verified every one of their 276,066 pixels
against MapleLib's decoded PNGs. The WZ incomplete-deflate/checksum limitation remains
explicit in the asset provenance report.

Evidence:

- `artifacts/southperry-scenery-assets/`: PNGs, payloads, dimensions and copy provenance.
- `artifacts/southperry-scenery-comparison/comparison.json`: all 27 comparisons,
  source/frame hashes, displacement controls and relative-translation checks.
- `artifacts/southperry-scenery-comparison/*-recorded.png` and `*-differences.png`:
  first-frame crops and opaque-pixel residual maps.
- `artifacts/southperry-scenery-verification.md`: run results and timing.

Rerun the comparison into a new output directory:

```powershell
.venv\Scripts\python.exe -m tools.compare_southperry_scenery --assets artifacts\southperry-scenery-assets --footage artifacts\southperry-reference\footage --bundle artifacts\southperry-dependency-source --output artifacts\southperry-scenery-comparison-new
```

Extraction uses the separate `tools/scenery_probe/SceneryProbe.csproj`, .NET SDK10,
and the existing clean local MapleLib checkout pinned to
`04570d43cd90e1b42f613226dd0be22ce58abd1c`. Build with `MapleLibRoot` set explicitly,
`PublishAot=false`, `UseSharedCompilation=false`, `NuGetAudit=false`, an existing NuGet
package cache and an empty local restore source. Run its DLL with a private staged copy
root and a new output folder. It accepts exactly the three fixed inline pictures
and rejects links/unsupported formats. This run opened only staged artwork copies;
no map or installed file was opened by the probe.
Both source/copy hashes were checked before and after extraction. The separate project
preserves the pre-existing dirty main extractor. MapleLib is GPL-3.0; this probe source
is GPL-3.0-only. The external Spine runtime has its own license; no dependency binaries,
game assets or recordings are committed or redistributed here.

Conclusion: these extracted scenery pieces are usable for direct pixel matching and
consistent alignment in the examined Southperry recordings. This does not verify
native client/build identity, character feet, minimap quantization, contact, collision,
navigation, live behavior or accuracy on unfamiliar maps. No safety/readiness gate or
runtime behavior was changed.
