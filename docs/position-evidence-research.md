# Position evidence research

Research date: 2026-11-01. Offline source review only; no game interaction.

## Projection: evidence and limits

**Finding:** a shared projection is plausible, but the examined primary source is a replacement client, not this server's native executable. HeavenClient calls itself a made-from-scratch client; its current README describes v83 server compatibility using newer v229.2 assets. Therefore its implementation cannot establish this client's exact marker origin, rounding or layout. [Project README](https://github.com/ryantpayton/MapleStory-Client/blob/cbb0fe27cf9683a12eca0a569121d8033cdc2a4d/README.md).

Reference source pinned to `ryantpayton/MapleStory-Client@cbb0fe27cf9683a12eca0a569121d8033cdc2a4d`:

| Verified reference-client behavior | Primary source |
| --- | --- |
| `UIMiniMap::update` reads `miniMap/mag`, sets `scale = 2^mag`, and reads `centerX/centerY`. `draw_movable_markers` projects player position plus center, then subtracts marker dimensions divided by `(2,0)`. | [UIMiniMap.cpp, lines 140–141 and 534–565](https://github.com/ryantpayton/MapleStory-Client/blob/cbb0fe27cf9683a12eca0a569121d8033cdc2a4d/IO/UITypes/UIMiniMap.cpp#L534) |
| `Point<int16_t>` division is integer division. Component-wise division treats a zero divisor as one: dividing dimensions by `(2,0)` produces `(width/2,height)`. | [Template/Point.h, lines 174–176 and 196–201](https://github.com/ryantpayton/MapleStory-Client/blob/cbb0fe27cf9683a12eca0a569121d8033cdc2a4d/Template/Point.h#L174) |
| Marker source is normally `Map/MapHelper.img/minimap/user`, with an alternate UI helper selectable. Canvas placement depends on dimensions/window layout; expanded mode adds an offset to both canvas and markers. | [UIMiniMap.cpp, lines 48–61, 432–531](https://github.com/ryantpayton/MapleStory-Client/blob/cbb0fe27cf9683a12eca0a569121d8033cdc2a4d/IO/UITypes/UIMiniMap.cpp#L432) |
| `Texture` reads each asset's `origin`; ordinary drawing subtracts that origin from the supplied position. Animation dimensions/origin come from its current frame. | [Texture.cpp, lines 25–55 and 70–81](https://github.com/ryantpayton/MapleStory-Client/blob/cbb0fe27cf9683a12eca0a569121d8033cdc2a4d/Graphics/Texture.cpp#L25), [DrawArgument.h, lines 114–138](https://github.com/ryantpayton/MapleStory-Client/blob/cbb0fe27cf9683a12eca0a569121d8033cdc2a4d/Graphics/DrawArgument.h#L114), [Animation.cpp, lines 293–299](https://github.com/ryantpayton/MapleStory-Client/blob/cbb0fe27cf9683a12eca0a569121d8033cdc2a4d/Graphics/Animation.cpp#L293) |

**Derived reference formula**, for ordinary unscaled frames, coordinates relative to the rendered canvas top-left:

```text
q = trunc_toward_zero((integer_world_position + map_center) / 2^mag)
observed_marker_center = q + canvas_asset_origin
                         - (marker_width//2, marker_height)
                         - marker_asset_origin + detected_center_within_marker
```

The last term depends on the detector's colored-pixel mask and center convention, not just the sprite canvas dimensions. A detected six-pixel component does not establish the complete asset size or origin. This formula is an algebraic consequence of the linked rendering methods; numeric origins for the user's native assets remain unknown.

## Quantization and trustworthy labels

The reference renderer first rounds physical position to integer world coordinates (`MovingObject::get_x/get_y`), then divides the shifted integer coordinates. [PhysicsObject.h, lines 117–143](https://github.com/ryantpayton/MapleStory-Client/blob/cbb0fe27cf9683a12eca0a569121d8033cdc2a4d/Gameplay/Physics/PhysicsObject.h#L117). Integer division truncates toward zero; do not silently substitute floor for negative shifted coordinates.

**Inference:** at scale 16, a usual positive projection bin contains 16 integer world coordinates per axis. Exact marker localization therefore does not recover exact world position. Report a world interval and additional screenshot evidence; ground/rope constraints can narrow it. Quantization and detection uncertainty are separate errors.

Trustworthy evaluation must keep these evidence classes separate:

- Public footholds, ropes, portals and asset origins are exact labels **within the identified exported map/build**. Matching that build to the native map still requires independent scene evidence.
- A deterministic reference-renderer fixture supplies exact synthetic labels and tests the documented formula; it cannot prove native-client accuracy.
- Native screenshot labels require an independently registered world reference with stated uncertainty. Coordinates produced by the same minimap formula or fitted bias are circular evaluation labels. A portal coordinate alone does not prove the player is exactly centered on it.

**Grounded next action:** inspect matching exported helper/canvas origin metadata if publicly available, retain the reference formula as a hypothesis, and compare it against held-out native screenshots using independently labelled scene geometry. Separate canvas registration, marker-mask origin and quantization residuals before replacing `MARKER_BIAS`. No reviewed source establishes pixel accuracy, universal map coverage or the user's actual native quantizer.

## Independent offline test material

The publisher's [public dataset specification](https://github.com/ohmi69/osms_datamine_dashboard/blob/main/data/api/v1/README.md) provides map records, portal/NPC/mob placements, minimap URLs and full-render URLs. Its [metadata](https://github.com/ohmi69/osms_datamine_dashboard/blob/main/data/api/v1/meta.json) declares client build `5236f08ecbb6e3f440ea49165834ecbe9927528e`, update `2026-10-29T15:56:20Z`, 336 map records and `maps.json` SHA-256 `35f699405361bc9a77650ce62f70e83f21fe3dd51f926935d968e7bd93589d41`. These are publisher-declared values, not verification that the operator runs that build. The [current records](https://github.com/ohmi69/osms_datamine_dashboard/blob/main/data/api/v1/maps.json) were read during this research. Do not substitute the existing local `classic-source-maps.json` bytes for this snapshot: that local file hashes to `9b2cbd11da50b158564028e0a6487f66ea02211baf39ea18d0196b69288f1148`.

### Coordinate frames must be verified

The public API specification describes placement coordinates as map-origin pixels, not image-corner pixels. However, the owning viewer applies the portal values directly to natural-image pixels, then scales them for display: [MapPortalOverlay.js](https://github.com/ohmi69/osms_datamine_dashboard/blob/main/tabs/maps/MapPortalOverlay.js). It similarly uses NPC/mob positions directly for full-image overlays: [MapBrowser.js](https://github.com/ohmi69/osms_datamine_dashboard/blob/main/tabs/maps/MapBrowser.js). The [viewer portal records](https://github.com/ohmi69/osms_datamine_dashboard/blob/main/data/current/portals.json) contain the same Southperry values as the public API. This is a coordinate-convention conflict for our use, not proof that either convention equals the native client's origin.

Comparing independently named type-2 portals in the existing raw MeowDB exports with those published image-placement records gives:

| Map / portal | Raw imported geometry (x,y) | Published placement (x,y) | Placement minus raw |
| --- | --- | --- | --- |
| Southperry / west00 | (-547,286) | (313,1841) | (860,1555) |
| Southperry / in00 | (699,527) | (1559,2082) | (860,1555) |
| Snail Hunting Ground III / east00 | (2753,-685) | (3163,410) | (410,1095) |
| Snail Hunting Ground III / west00 | (-19,274) | (391,1369) | (410,1095) |

These are exact arithmetic relationships between the reviewed exports. Raw sources: [Southperry map page](https://meowdb.com/msclassic/maps/000000060), [Snail Hunting Ground III page](https://meowdb.com/msclassic/maps/000000042), and retained `artifacts/meowdb-000000060-export.json` / `artifacts/meowdb-000000042-export.json`. The complete local exports hash to `75f76d923b5d96fb48642eada0e528f6ecfd3a54975b5ee8526ac4c3323290b4` and `e91516bfee9ad61fcca81d3193da29cbd4071f8703cf4e2e74fa07d3ef43de61` respectively.

**Inference:** the full-render images can be useful world-labelled test material once their image-to-geometry transform is explicitly checked. Do not assume the image begins at `VRLeft/VRTop`, or copy API placement values into the imported geometry's frame. The two reviewed maps have different offsets. A future corpus builder should require at least three independent, non-collinear named anchors per new map, verify scale/orientation/residuals, and reject inconsistent source versions. Do not reuse portals with duplicate names as if their identity were unique.

Direct web-tool reads of the MeowDB terrain JSON endpoints for Southperry and Amherst returned an internal inaccessible-resource error in this research. No alternate-client retry was attempted. The reviewed existing exports remain usable evidence; raw terrain for the proposed new maps has **not** been acquired or compatibility-verified here.

## Proposed fresh-map reserve

Selection used metadata only. No full-render image below was downloaded, displayed or evaluated during this research. Candidate IDs differ from the original benchmark and known development maps; named scene aliases must still be checked when sealing the corpus. All six have at least three type-2 portals in the reviewed public records, making coordinate cross-checking plausible. Portal counts alone do not prove source compatibility or non-collinearity of raw counterpart anchors.

| Map ID (nine digits) | Publisher's name | Type-2 portals | Full-render resource |
| --- | --- | --- | --- |
| 000001000 | The Field West of Amherst | 8 | [content-addressed render](https://osmsdataexplorer.com/data/maps/f926f99474bcdc6657acb5342bfa6ebe.webp) |
| 010000020 | 3-Way Road-Split | 3 | [content-addressed render](https://osmsdataexplorer.com/data/maps/d6561e47426d936ea7f98ca62baa715f.webp) |
| 010004020 | West Rocky Mountain I | 3 | [content-addressed render](https://osmsdataexplorer.com/data/maps/74ab9534468225f3e4aa6f40cd8850b3.webp) |
| 010005010 | Swampy Land in a Deep Forest | 4 | [content-addressed render](https://osmsdataexplorer.com/data/maps/380a313101f1922c5e3a5424e557e6f3.webp) |
| 010002000 | Ellinia | 6 | [content-addressed render](https://osmsdataexplorer.com/data/maps/93f41fc2034fcaf4f6444dfd0f8e695b.webp) |
| 010000000 | Lith Harbor | 4 | [content-addressed render](https://osmsdataexplorer.com/data/maps/395db7d03cb5d4bec0d020c1f1fe6b4f.webp) |

This reserve is four fields and two towns according to the publisher's `is_town` metadata. It is a **proposed rendered-map corpus**, not newly collected native footage or an accepted benchmark. Preserve these maps for evaluation; use other layouts for further development. Freeze asset/build hashes and the split before inspecting the evaluation renders or changing detector thresholds.

Local recording audit: nonempty `catalog.active_map` values across the existing decision logs were only Snail Hunting Ground III, Southperry and Tree Dungeon, Forest Up North I. There were 105 rows without a map name. The previously unmapped clip `session-1793487201097188400-clip` starts with a desktop/debugger screenshot rather than a game scene; its first frame was inspected and cannot establish a map. This audit supports reserving the proposed names but is not a complete proof about every historical frame. Check remaining unknown rows and cross-provider aliases before claiming strict non-overlap. In particular, Classic Henesys Park is `010001050`, while the old saved DreamMS area uses `100000200`; differing IDs alone are not a sufficient split.

## Recommended evidence ladder

1. **Coordinate/data checks, offline:** archive a compatible source snapshot and verify raw-world to full-render transforms. Stop on mismatches instead of fitting a per-map correction into runtime code. Data provenance checks are dataset preparation, not operator map teaching.
2. **Exact synthetic answers, offline:** crop verified full renders at chosen camera positions and composite a shared actor asset with a declared foot origin at chosen world positions. The generator emits the answers from the drawing coordinates, never by calling the locator. Keep its camera/actor/label metadata inaccessible to the runtime locator. This can test unseen-map geometry and vision with exact constructed labels; it does not certify native player-foot offsets, UI behavior, animation, camera motion, collisions or route success.
3. **Shared projection audit, offline:** obtain matching minimap/canvas/marker asset-origin metadata if available and compare the primary-source formula with independent evidence. The reviewed replacement client is a hypothesis source, not a reason to replace `MARKER_BIAS` or remove uncertainty.
4. **Native acceptance later:** independently check the actual client's coordinate/foot convention and observed route behavior in an explicitly authorized supervised batch. Keep screenshot measurements, constructed ground truth and observed gameplay results separate.

No reviewed primary source supplied a ready-made set of this operator's native screenshots paired with independently verified four-pixel world positions. Therefore no new native accuracy or routing acceptance can be claimed. The useful research result is a concrete source/reserve and coordinate-validation method, with the missing native evidence named. No code, game session, saved map, calibration or safety gate changed.
