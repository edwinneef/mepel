# Input and automation reliability

Research date: 2026-11-01. Static source review only; no key input, controller test, restart or gameplay session was run.

[Index](README.md) · [architecture](architecture.md) · [combat](combat.md) · [navigation](navigation.md) · [source audit](evidence-general-systems.md)

## Current implementation already provides the critical boundary

[KeyboardController](../../../src/maplebot/keyboard.py) is the sole gameplay input owner. It has a held-key set, queued plans and tickets, generation-based cancellation, scheduled down/up events, movement leases, an executor thread and an independent watchdog. `stop` disables input, changes the generation, cancels queued work and releases keys. `suspend` supports recognition recovery while keeping physical safety monitoring active. `_execute_schedule` has cancellation checks and a `finally` release path.

[Win32Input.send](../../../src/maplebot/keyboard.py) uses scan-code SendInput and checks the accepted event count. This detects submission failure, **not** whether the game consumed the event, moved the player, or registered a hit. `_send` records issued/finished clocks, event sequence and history identity; `timing_snapshot` reports dropped history as well as retained events. Those distinctions should survive any new action abstraction.

[Arbiter.choose](../../../src/maplebot/scheduler.py) is pure: it prioritizes sustain, excludes simultaneous combat/navigation, and waits on relevant in-flight tickets. Stops bypass ordinary arbitration. An urgent potion does not interrupt an already active bounded plan. This is an explicit policy with a bounded delay, not a general preemptive scheduler.

Reviewed tests include [test_keyboard.py](../../../tests/test_keyboard.py), [test_scheduler.py](../../../tests/test_scheduler.py), and [test_recorder.py](../../../tests/test_recorder.py). Their source covers queue ordering, cancellation, recording of events completed between frames, and ownership/lifecycle behavior. Reading tests does not establish their current passing result or native key delivery.

## External patterns worth understanding

| Pattern | Source evidence | Reliability benefit | Limits / local decision |
| --- | --- | --- | --- |
| Priority selector invalidates lower-priority work | py_trees [Selector.tick](https://github.com/splintered-reality/py_trees/blob/786859dcafc4ec9b78ff7ed0950b106c829d2174/py_trees/composites.py#L372) | Explicit interruption semantics | Only tree state changes unless the leaf releases/cancels its controller ticket |
| Lifecycle exit hook | py_trees [Behaviour.stop](https://github.com/splintered-reality/py_trees/blob/786859dcafc4ec9b78ff7ed0950b106c829d2174/py_trees/behaviour.py#L344) calls `terminate` | One cleanup contract for success, failure and invalidation | Cooperative; a blocked update can delay the next tick |
| Bounded visual wait | Airtest [loop_find](https://github.com/AirtestProject/Airtest/blob/d729c631d2032521be1e2168a249a2a89d79af2a/airtest/core/cv.py#L40) | Timeout and screenshot on failure | Blocking polling and wall-clock timeout are not appropriate replacements for the engine's guarded control loop |
| Evidence-rich action report | Airtest [LogToHtml._translate_step](https://github.com/AirtestProject/Airtest/blob/d729c631d2032521be1e2168a249a2a89d79af2a/airtest/report/report.py#L129) | Connect action intent, image, assertion and failure | A report still needs a meaningful outcome assertion |
| Track lifecycle independent from detection | Norfair [Tracker.update](https://github.com/tryolabs/norfair/blob/e517b4236f6b67a6ecf342f5df1fccb7788dbc54/norfair/tracker.py#L144) | Perception loss need not erase identity immediately | Retaining identity must not retain gameplay permission indefinitely |

The transferable idea is **explicit cancellation ownership**, not importing a framework. py_trees is BSD-3-Clause; Airtest is Apache-2.0, but the inspected Airtest dependency ranges conflict with our NumPy/OpenCV declarations. Full dependency details are in the [source audit](evidence-general-systems.md).

## State machines versus behavior trees

| Criterion | Existing state machines plus arbiter | Behavior tree |
| --- | --- | --- |
| Reliability | Existing safety owner and bounded actions | Requires carefully implemented nonblocking leaves and termination |
| Accuracy | Depends on observation/effect evidence, not state-machine syntax | Same |
| Performance | Small fixed control cost; no measured bottleneck identified | Usually small tree traversal cost; no local benchmark |
| Complexity / integration | Preserve current tickets, leases and pure decisions | Adapter, migration and more lifecycle states |
| Maintainability | Good while task branches remain understandable | Helpful for many reusable conditional behaviors |
| Maturity | Local implementation and focused test sources | Mature generic library, no automatic Maple safety |
| Relevance | High now | Conditional future option, not recommended rewrite |

A tree may eventually organize class-specific routines or complex objectives, but it should still emit plans to the same keyboard owner. It must never own raw key-down calls independently.

## Timing and observed effects

Keep these stages distinct in logs and acceptance criteria:

1. Perception frame was captured and interpreted.
2. Policy selected an action using a particular observation.
3. Scheduler queued and executor started the ticket.
4. Backend accepted down/up events.
5. Subsequent screenshots show movement/attack consequences.
6. Combat evidence supports hit/death, or remains unknown.

Elapsed time should use a monotonic clock. Variable screenshot intervals require elapsed-time motion prediction and action deadlines; frame counts alone change meaning when perception stalls. Use measured key-dispatch timing as input history, not proof of physics or damage.

Simultaneous key handling belongs in an explicit schedule with down/up ownership. A new movement/combat feature must not directly issue keys from perception threads, a behavior-tree leaf or a debug callback. Cancellation should invalidate queued plans, release held state, and prevent an old callback from releasing a later owner's key.

## Recovery under uncertainty

The existing watchdog, focus check, F8, overlay lease, capture-only mode, release behavior and map/player gates are constraints. External scripts that continue key sequences after image failure offer no justification to weaken them.

Use a bounded recovery state with explicit entry reason, observation requirements, elapsed deadline and terminal result. Predicted player position may guide the next search ROI; it cannot establish fresh player identity or a confirmed landing. Separately, current combat permits bounded in-place attacks on a previously acquired, briefly hidden enemy; prediction does not create a new target or confirm a hit. See [combat](combat.md). When independent player evidence recovers, confirm stable identity before resuming through existing gates. Preserve first-failure termination for live batches.

Unexpected map/layout transitions invalidate coordinates, track history and pending action assumptions. An input rejection or failed focus request should be reported rather than repeatedly retried. This audit proposes no change to those operational rules.

## Practical improvements and verification

- **Outcome-linked ticket timeline:** extend existing event history/reporting so a ticket points to the input observation and subsequent visual evidence. Test missing/late frames and unknown outcomes explicitly; do not infer success from ticket completion.
- **Cancellation contract coverage:** for any newly introduced action owner, test stop during queueing, active multi-key holds, perception suspension and cleanup. Reuse existing controller tests instead of adding a second input backend.
- **Stale-observation diagnostics:** measure observation age when dispatch occurs and identify actions based on old frames. Change a threshold only after inspecting real latency and existing freshness gates.
- **Recovery reason visibility:** distinguish low image confidence, identity ambiguity, camera uncertainty, map mismatch and backend refusal. Each needs a different evidence check, not a generic retry.

These are incremental follow-ups. The recommended next implementation milestone remains the one in [improvement-backlog.md](improvement-backlog.md); no runtime behavior was changed.

