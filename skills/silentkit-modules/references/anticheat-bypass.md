# Anticheat bypass and validation

Use this reference for detector-facing action validation and candidate bypass experiments. General module state,
ownership, navigation and packet-queue mechanics live in the [main skill](../SKILL.md); module-specific strategies,
prerequisites, failure triggers and test cases live in [modules.json](modules.json). Keep this the single detailed
anticheat reference rather than creating one troubleshooting document per automation feature.

## Evidence and scope

The server has authoritative world state, permissions, plugin rules and observed traffic. Physically consistent
inputs reduce some implementation errors; they do not prove automation is indistinguishable or accepted. Added noise,
rare activation, low CPS, a field named "legit", or a clean local diagnostic are not bypass evidence. A server-side
policy can reject automation even if the action is physically possible.

For each experiment record the client/game/protocol build, server configuration when known, enabled modules, real
latency/jitter, effects/attributes and relevant permissions. Distinguish:

- **Source-confirmed constraint:** the supported version's actual input, action or packet path was inspected.
- **Deterministic validation:** fixtures/simulations check an invariant, including failure and cancellation paths.
- **Hook verification:** the production transformer inserted the named hook at the actual version's required anchor.
- **Live observation:** a real action/result was observed, with attempted, predicted and confirmed states separated.
- **Server-issued finding:** a check name/violation and its source were actually supplied. A chat keyword, client
  heuristic or position correction alone does not identify a specific anticheat check.

No activity on an idle/stopped server is not a clean run. Lack of visible alerts does not establish acceptance. Keep
server-specific conclusions scoped to the implementation and configuration observed; do not transplant thresholds.

## Detector families

| Family | Relevant inconsistency | Candidate strategy and its limit |
|---|---|---|
| Movement prediction | Position/velocity cannot be reproduced from authoritative state and consumed input | Reproduce integration, collision order, abilities/effects, sprint and item/fluid modifiers; a client-only permission or attribute change remains unsupported. |
| Rotation analysis | Off-contract quantization, discontinuities, inconsistent target tracking or impossible action rays | Validate every final contributor and the actual sent rotation; curve/noise tuning remains an experiment, not a proof. |
| Click timing and action order | Stale clicks, repeated intervals, wrong item/cooldown or an impossible sequence | Validate each dispatch, use a monotonic clock, observe real consumed actions and compare with a relevant baseline. |
| Reach, direction and visibility | Actual eye ray misses the real hitbox/face or exceeds current allowed interaction range | Use real geometry and permissions at action time; a larger local box or projected point cannot authorize extra reach. |
| Knockback/explosion response | Resulting movement differs from the server-issued impulse and collisions | Measure the original impulse and result. Partial/chance/jittered reduction still changes the trajectory. |
| Block interaction | Break/place state, support, hit point or timing disagrees with the world | Carry one validated candidate through aim and use; observe acknowledgements/world changes before dependent steps. |
| Packet clock/order | Extra movement clock advancement, split batches or reordered dependent actions | Preserve actual protocol tick boundaries, sequence and control barriers; bounding a queue does not guarantee acceptance. |
| Corrections and latency | Actions continue from a stale location, control packets stall, or delayed state exceeds the observation window | Apply corrections normally, invalidate old plans, measure actual RTT/jitter and back off rather than inventing a ping allowance. |

Determine which families the target configuration actually implements. Prediction, heuristic and statistical
detectors can coexist and change by version/configuration; do not infer their exact checks from a product name.

## Click validation

Validate immediately before **each** primary, assist, repeated or pending second click:

1. The module/task still owns the action and belongs to the same player/world/session and current engagement.
2. Manual input policy still permits the action; release, menus, focused text entry, pause, focus policy or takeover
   by another owner cancels pending work instead of allowing one last click.
3. The held item, selected-slot lease, item-use state and current charge/cooldown still satisfy that action's rules.
4. The actual target remains alive/present/allowed, with current reach, visibility and attack geometry. Aim-ready,
   on-crosshair and in-range settings apply to assist/second clicks too; an assist path must not bypass them.
5. The rotation used by that action is the one already applied/sent in the target version's required order. A later
   camera update cannot validate an earlier attack. A use/interact packet may carry its own rotation separately.
6. The deadline's units match the clock, any per-action budget counts real dispatches, and the action has not already
   been consumed by another path.

Keep eligibility in one final action adapter shared by scheduling paths. Clear pending work on disable/re-enable,
context replacement and prerequisite loss; resuming a module must not release a stale double click. Use an explicit
monotonic clock, e.g. `nowNanos + delayMs * 1_000_000L`. A separate cooldown can hide a units bug, so test the deadline
itself. Count generated, cancelled, attempted and consumed clicks separately. Discard catch-up work after stalls.

Optional double-click, fatigue, burst or rhythm modes should retain the configured rate meaning. Compare generated
intervals and actual action packets; device-style labels or random gaps do not prove a human distribution. High
render FPS does not authorize more protocol ticks. One action per tick is a task budget, not a universal engine rule:
an abort-old/start-new mining sequence can legitimately contain several actions. Inspect type and order first.

## Rotation output

- Repair estimator state before adding noise. Do not differentiate across target identity changes, teleportation or
  long gaps. Keep target-motion estimation separate from camera momentum and seed new target samples on reacquisition.
- Use elapsed-time filters (`alpha = 1-exp(-dt/tau)`) and scale stochastic decay/innovation consistently. Fixed frame
  coefficients behave differently at different FPS. Drop stall catch-up rather than advancing many missed steps.
- Bound the **final combined output** after feed-forward, overshoot, shake and drift. Apply disabled-axis constraints
  last: disabling vertical assistance means zero emitted assisted pitch even if shake is enabled.
- Use one version-appropriate mouse-count path with carried fractional counts for all contributors. An independent
  fractional click-jitter path or a second quantizer can invalidate a clean aim controller. Observe desired/eased,
  applied and actually sent rotation separately; floating-point serialization and version input math matter.
- Keep led/drifted points inside the actual permitted hitbox. Moving the box itself can make a closest-point method
  return a point outside the real target. Recheck occlusion/range after selecting the point.
- Retain a valid target unless another score improves materially; invalidate immediately on death/filter change.
  Use an on-target hysteresis zone and a stable body point rather than chasing tiny per-frame center changes.
- During navigation, follow the route camera rather than tracking an unreachable opponent through an obstacle.
  Melee tracking needs reach and a usable line of sight; release it while a route is blocked. Preserve acceleration
  through ordinary replans and reset stale velocity/count state after losing ownership or changing sessions.
- If testing speed variation, measure it at the cadence actually sampled by the protocol, not merely at the render
  frame. Rate caps and competing contributors can dominate the resulting distribution. No jitter amplitude or fixed
  turn ceiling is a universal anticheat threshold.

Compare final output at 30/60/144/240 FPS, irregular frames, stalls, yaw wrap, pitch bounds, sensitivities, moving and
stationary targets, target switches, teleports and competing owners. Assert speed/acceleration limits, zero disabled
axes, in-hitbox points and no stale estimator after yielding. Use seeded randomness and fake time where appropriate.

## Reach, placement and mining

For an attack, test the actual eye ray against the real target box and the current allowed interaction range; a
distance to entity feet or a broad angular dot product is not enough. A historical/expanded client box remains a
local estimate. Clamp/projecting a selected point does not establish that the server's actual ray intersects it.

For placement, carry `{target, support, face, hitPoint}` unchanged through selection, alignment and execution. Sample
an optional face point once and reuse it. Check replaceability, body collision, held item, reach and a ray to the
actual supported face; test alternate legal neighbors. A conservative full-face policy can reject valid partial
surfaces, so do not describe every slab/fence as universally unclickable. World acknowledgement, attempted use and
an interaction that opens a menu are different outcomes. Revalidate every dependent place/charge/use step.

For breaking, prefer the supported held-attack pipeline over inventing extra completion packets. Keep the rendered
crosshair, actual packet rotation and selected break target consistent. Commit appropriately for slow blocks; allow
continuous instant-breaking only when the game's rules and real reach permit it. Resolve occluders, stop repeatedly
rejected/protected blocks and distinguish local predicted completion from server-confirmed removal. Avoid arbitrary
per-block delays as a substitute for validating the action itself.

## Movement and state consistency

Use the final consumed normalized input, current momentum and full player body in prediction. Include effects,
equipment, fluid/climb/bounce transitions, collision order and server-provided ability speeds. Validate braking paths
as well as forward acceleration; independent clear axis rays do not prove a combined diagonal/vertical move is safe.

Separate sprint entry, retained intent, actual engine sprint and the synthetic key press. Reapplying an entry heading
gate during continuation can cause repeated start/stop packets. Preserve a valid latch where the supported engine
does, observe a bounded normal start, and respect real cancellations. Do not repeatedly set a field true to override
the engine. Generic sprint and task-owned sprint must not compete. Authorized-flight ascent pulses may interact with
the manual double-tap toggle; fix that narrowly within task ownership, preserving manual behavior elsewhere.

Changing step height locally, ignoring item-use slowdown or reducing knockback can still disagree with server state.
Chance, partial percentages and float jitter do not make an unsupported trajectory predicted. Check the authoritative
permission/mechanic first; otherwise classify the strategy as experimental/high-risk rather than a proven bypass.

## Packet order and corrections

Use the [main queue contracts](../SKILL.md#lifecycle-races-replay-and-observability): originating generations,
monotonic sequence cutoffs, owner-consistent rules, one-use replay identity, protocol batches, callback completion and
bounded age/count/bytes. A zero-delay return is ineffective if an earlier indefinite head still blocks control traffic.

Observe actual dispatch once; attempted send plus replay is not two packets. Keep keepalive/transaction, disconnect,
configuration, teleport acknowledgements, prediction and container state out of arbitrary holds. Preserve the target
version's tick-end marker with its movement batch. Define drain/discard behavior at world and protocol barriers.

Apply server corrections and their acknowledgements normally, invalidate pre-correction actions/routes and establish
fresh baselines. A bounded recovery may settle/replan through normal inputs; repeated corrections, missing permissions
or failed acknowledgement should stop the task. Touching ground or walking a short distance is not evidence that a
server's suspicion/violation state reset. Never suppress correction processing to make a local trace look clean.

Measure real RTT, jitter and observed spikes. An assumed `lag_window - ping` formula is not a universal allowance for
old positions, backtrack or delayed combat. Delaying/forging latency measurements or accelerating the packet clock
does not create extra permission. Compare normal and automated runs under the same measurable conditions.

## Calibration and reporting

Start with a relevant manual/unmodified baseline, isolate one module and one candidate change, then add combinations
sharing camera, attack, movement or packet rules. Capture input intent, engine-applied state, final packet order,
corrections and available server-issued check names/values on one timeline. Mark intervals with actual activity.

Test failure cases as seriously as smooth runs: release before a pending click, target replacement, occlusion,
menu A-to-B, owner takeover, disconnect/rejoin, correction between aim and action, protected blocks, stale producers,
long tasks followed by a queued capability, missing acknowledgement and exhausted path budgets. Use actual supported
classfiles for hooks and independent start-state comparisons for physics. Report what each layer establishes and
leave server acceptance unverified when a matching live observation is unavailable.
