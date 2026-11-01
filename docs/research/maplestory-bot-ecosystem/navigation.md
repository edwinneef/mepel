# Navigation, movement and world localization

Research date: 2026-11-01. Source inspection only. Existing source was assessed before external alternatives. Repository snapshot dates, licenses and complete inspected-file lists are in [navigation source evidence](evidence-maple-navigation.md); player identity is covered in [player tracking](player-tracking.md).

## Current implementation: preserve its contracts

The core is Python despite the React/TypeScript workbench. [moves.py](../../../src/maplebot/moves.py) generates walk, jump, drop and climb proposals from imported footholds and ropes. `Move.trace` contains launch/landing/corridor points; constants bound rise, gap and insets. These are geometric reachability proposals, not an identified physics model. `generate` chooses the simplest move per source/target pair and checks which platform lies underneath a fall.

[navigation.py](../../../src/maplebot/navigation.py) separates computed/proven edges, exclusions, map revision/fingerprint and route validation. `RouteMap.plan` uses a heap of accumulated travel plus transition cost, maintaining edge-depth alternatives within an eight-edge limit. This is a bounded uniform-cost-style search, not a missing A* implementation. Replacing it with an A* package has no demonstrated payoff at this graph size. A better heuristic also cannot make an unproven edge physically safe.

[navigation_executor.py](../../../src/maplebot/navigation_executor.py) already includes `Navigator`, `Feedback`, bounded approach/edge deadlines, short movement pulses, settled-origin/arrival checks, progress checks and replanning. The executor distinguishes being near a rope from observed progress on it. `EdgeStep` is a separately bounded recovery. [navigation_runtime.py](../../../src/maplebot/navigation_runtime.py) owns runtime integration and recognition recovery; [navigation recovery tests](../../../tests/test_navigation_recovery.py) cover release on flicker, no resumption after hard failure/operator stop, fresh identity corroboration and limited marker-only flight feedback. [executor tests](../../../tests/test_navigation_executor.py) cover departure and settled destination rather than accepting prediction as arrival. These tests were read, not rerun for this documentation task.

[motion_learning.py](../../../src/maplebot/motion_learning.py) already collects passive, lifetime-tagged input/position evidence. `PassiveMovement.observe` rejects history gaps and mixed controls; `snapshot` deliberately leaves speed, braking, jump and climb unidentified. Do not recommend adding motion collection as if absent or promote median observed speed into controller authority. [tools/calibrate_navigation_physics.py](../../../tools/calibrate_navigation_physics.py) and the [offline harness](../../offline-navigation-harness.md) are the existing integration points for future evidence.

Existing [bounded-navigation acceptance notes](../../bounded-navigation.md) distinguish installed/offline checks from pending native acceptance. No new game run was performed here.

## Competing approaches

| Approach and inspected implementation | Reliability / accuracy | Cost and complexity | Compatibility / maintenance | Decision |
| --- | --- | --- | --- | --- |
| Taught minimap points and teleport-neighbor A* variant: easymaple `Layout.shortest_path` | Useful when classes and map point density match; no terrain or landing proof | Small tree/heap; low-to-medium implementation effort | Teleport assumptions do not match Classic walking/jumps; root reuse license unverified | Keep as teaching-interface reference only |
| Action-colored routes: LinPolly `update_cmd_by_route` | Reactive at each position; nearest marker can switch unexpectedly after knockback; stale coordinates risk stale commands | Local pixel scan; simpler than a physics graph | Class/map-specific authoring; MIT source, but our gate contracts still needed | Consider route visualization/authoring, retain graph executor |
| Compressed recorded observations: sychen `recording.route.compress` | Preserves turns and settled level changes; recordings do not prove future movement | Linear trace processing; modest offline cost | Fits our replay/proof records; no copying license found | Useful proposal-generation experiment, never auto-proven links |
| Full-screen YOLO platforms/ladders: TinForge | Broad classes in one pass; incomplete boxes can split/merge surfaces | Model inference, training, packaging and accelerator burden; unmeasured | Surface identities/collision rules still needed; third-party model rights unresolved | Experimental annotation aid only |
| Current imported-geometry graph plus fresh visual localization | Exact within the identified map export, with native registration/edge uncertainty | Small graph search; perception dominates only if measured | Existing tests, proof store, revision and stop behavior | Preserve and improve evidence |

These cost descriptions are architectural estimates, not benchmark results. No inspected project supplies a transferable end-to-end Classic route-success rate.

### Source details that matter

[easymaple `Layout.shortest_path`](https://github.com/wanliAlex/easymaple/blob/af23f1d44e1e3adfe237c7612464f4dfc99362d3/src/easymaple/routine/layout.py#L141) picks a closest candidate from directional teleport neighborhoods. It appends the target even when its fringe empties. Its [Move and Point](https://github.com/wanliAlex/easymaple/blob/af23f1d44e1e3adfe237c7612464f4dfc99362d3/src/easymaple/routine/components.py) use an action counter but no explicit success result before point commands. This is practical feedback around scripts, not certified platform navigation.

[LinPolly route/ladder code](https://github.com/LinPolly/MapleStoryAutoLevelUp/blob/3e19173f8da5aab8405307bb9c6e3741dd3abd6b/src/engine/MapleStoryAutoLevelUp.py#L1441) merges horizontal and vertical route marks at ladder ends. Ladder status is inferred from screen `dx < 3` with nonzero `dy`; camera motion or knockback can satisfy that heuristic. Its random recovery does not prove a safe escape. The useful lesson is explicit approach/attachment/climb/exit phases, which our executor already substantially implements.

[sychen `_climb`](https://github.com/sychen6192/maplebot/blob/320234a21e90c0ee3a811ede71585a1ef627efc9/maplebot/brain/fsm.py#L442) checks minimap-y progress, limits repeated attempts and can give up on unreachable route levels. Its [_check_stuck](https://github.com/sychen6192/maplebot/blob/320234a21e90c0ee3a811ede71585a1ef627efc9/maplebot/brain/fsm.py#L587) resets when continuous patrol observations are interrupted. This avoids treating time spent attacking as failed movement. Our candidate verification should likewise pair expected progress with actual owned action intervals.

[D4MXD `move_target`](https://github.com/neiamo/D4MXD/blob/e50471e95028ba7c87cb4346d21a8c8954b0160f/maple_v2/actions.py#L45) returns true after a timed rope key sequence. That boolean is dispatch completion, not attachment or landing. Its README's A* claim belongs to POE2, not the inspected Maple subsystem.

## Minimap versus full-screen localization

Minimap localization survives foreground occlusion of the player and usually ignores sprite animation. It loses detail through marker size, projection quantization, overlapping markers, minimap scrolling and uncertain canvas origin. Full-screen localization supplies feet, facing and scene context but fails under bridges, effects and foreground objects. Neither supplies authoritative world coordinates without a verified transform.

Our [minimap.py](../../../src/maplebot/minimap.py) already segments the minimap and estimates terrain movement. `terrain_motion` scores bounded integer translations over textured pixels; it explicitly avoids bright moving-marker bias. [localization.py](../../../src/maplebot/localization.py) already contains `MinimapTransform`, scene matching and `MinimapTracker`. [map_alignment.py](../../../src/maplebot/map_alignment.py), [live_position.py](../../../src/maplebot/live_position.py) and the [position evidence research](../../position-evidence-research.md) cover additional registration and coordinate uncertainty. Do not add another unexplained coordinate space.

[sychen `MinimapScroll.update`](https://github.com/sychen6192/maplebot/blob/320234a21e90c0ee3a811ede71585a1ef627efc9/maplebot/vision/minimap_scroll.py#L131) masks current/previous dots, uses a Hann window and phase correlation, then subtracts terrain shift from the running origin. Low response or excessive shift resets the origin. This supplies a useful **challenger** for held-out scrolling clips; it is not automatically better than our textured matching. A reset must invalidate the former coordinate basis and its geometry association.

[D4MXD `find_yellow_dot`](https://github.com/neiamo/D4MXD/blob/e50471e95028ba7c87cb4346d21a8c8954b0160f/maple_v2/minimap.py#L25) combines HSV, area, circularity and continuity. Its missing-data branches can return the previous point without aging it. Use component shape as supplementary evidence, not that freshness behavior. Small markers can disappear under a 3×3 morphology operation; test actual client-sized dots before adopting morphology.

### Recommended hybrid, as an incremental refinement

Keep map/build identity, minimap transform and camera registration separate. Preserve fresh observation time, projected interval/error, track identity and evidence origin through each fusion result. Use a valid minimap fix to constrain candidate screen regions during a bridge occlusion; use fresh nametag/sprite evidence to confirm identity and feet when visible. If cues disagree or the transform basis changes, pause rather than averaging incompatible frames. Predicted intervals may guide search, but cannot certify rope grip or landing.

This is a recommendation to evaluate the current fusion, not a claim that it is missing. The next milestone is selected centrally in [the index](README.md); no gameplay or new calibration is authorized by this report.

## Physics, boundaries and geometry

No inspected bot supplied a validated Classic physics estimator covering acceleration, braking, airborne steering, landing, slopes and rope attachment. Published client/server constants or modern flash-jump command books cannot fill that gap. Our current fixed reachability constants should remain conservative, versioned assumptions until command-aligned recordings establish an appropriate model.

Useful future experiments are held-out jump-envelope prediction with uncertainty, action-conditioned movement progress, and systematic boundary/portal exclusion checks. Before any model influences control, compare predicted landing intervals with independent observed landings and report unsupported move classes. Static/platform visuals do not establish collision behavior; dense foreground edges are especially misleading.

Map stitching is useful only when registration is stable and source identity is preserved. Prefer current imported geometry and map-specific transform evidence over building a second world map from accumulated unbounded image translations. A stitched image may be a diagnostic backdrop; it must not become route authority because it looks continuous.

## Verification and unresolved questions

Use saved failures and existing replay first. Label independently: marker center and visibility, player feet/identity, camera shift, occlusion class, rope progress, departure and settled arrival. Measure position error, false certainty, wrong-platform assignment, time to reacquire and stale-coordinate reuse. Split by session/map, not adjacent frames from one clip. Explicitly include player hidden while minimap remains visible, both hidden, map switch, minimap resize and camera clamp.

Route verification must separate geometrically proposed, simulated, dispatched and natively observed transitions. Measure false arrival and unintended input after uncertainty as failures even when route completion improves. Reuse unchanged accepted controls and maps. Any later native batch requires the operator's explicit authorization under [AGENTS.md](../../../AGENTS.md).

See [architecture](architecture.md), [backlog](improvement-backlog.md) and [open questions](open-questions.md) for prioritization and remaining evidence.
