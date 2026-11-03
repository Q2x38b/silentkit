# Flight mining: practical consistency rules

Read for a miner using server-authorized creative-style flight. Elytra, ground sprinting and unauthorized flight
have different rules. The sprint-latch and jump-timer details below were checked against vanilla 26.2/26.3; inspect
the supported game's source/classfiles before applying the same hooks to another version.

## Sprint flight: a tap is not a continuously held key

- In these versions, ordinary run-sprint continuation needs positive forward impulse and valid movement state.
  Releasing the sprint key does not clear the latch. Forward+strafe, yaw changes and flight ascent/descent can retain
  sprint; they are not themselves reasons to send a sprint stop.
- Separate **entry preference**, **latched sprint intent**, **actual vanilla sprint** and **sprint-key state**.
  Start after a few consecutive eligible input ticks, press the ordinary key, then release it when vanilla reports
  sprinting. Preserve an already active manual sprint when the candidate input is safe.
- A route heading threshold is useful for deciding when to start. Reapplying it as a continuation requirement can
  create stop/start chatter every time the aim rakes sideways or a new route is selected. Retain the latch against
  actual final forward input and boosted collision clearance instead.
- Do not force `setSprinting(true)` after vanilla cancels it. Respect the interruption, impose a restart cooldown,
  and fall back to normal flight after repeated unacknowledged starts. Stable entry must count ticks, not duplicate
  render queries; initialize/reset clocks on world changes and input gaps.
- Final steering may veto a requested boost. Do not let “not sprinting yet” veto its own warmup: that resets the
  stable-entry counter every tick and prevents sprint from ever starting.
- Real stops remain important: no forward input, major collision, emergency counter-steering, menus, pause, loss of
  flight permission or boundary recovery. Never keep speed solely to satisfy a minimum sprint duration.
- Let one subsystem own sprint. A generic KeepSprint module must yield while the miner supplies its own flight
  input; vanilla forward-double-tap must not immediately restart a sprint the miner intentionally released.

One locally tested tuning used six eligible input ticks before a new press, three ticks to observe vanilla's latch,
a 20-tick restart cooldown and fallback after three unacknowledged/interrupted starts. Those are control-stability
examples, not anticheat thresholds; preserve a valid existing manual latch without making it wait through entry again.

## Predict the input the game will actually consume

- Read the server-provided flying speed. In the checked versions, sprint flight uses twice that horizontal input
  acceleration; it is not the ground sprint attribute's 1.3 multiplier. Include the doubled acceleration for
  retained **diagonal** sprint input as well as straight flight. Normalize diagonals as vanilla does.
- Preserve the target version's integration order: input acceleration, movement/collision, then drag for the next
  tick where applicable. Applying drag before displacement underestimates travel. Compare explicit start-state
  traces against vanilla, including modified flying speeds and effects; a self-consistent simulator can still be wrong.
- Check current momentum, a candidate impulse and a realizable counter-steer to rest. A long unsteered coast can be
  unnecessarily conservative; a center-line ray can be dangerously optimistic.
- Check the full body plus an inset inside the surveyed enclosure, not just the player's block or crosshair. For
  simultaneous horizontal/vertical input, check intermediate heights too: independent clear horizontal and vertical
  rays do not prove the combined body motion clears an overhang.
- Keep reachable forward mining faces preferred throughout a retained sprint, including route handoffs and altitude
  adjustments. Otherwise selecting a side/behind target can turn the camera enough to remove forward input and undo
  the latch fix. This is a preference among valid faces, not permission to aim outside reach.

## The jump-double-tap trap

Flight ascent uses jump input. Short controller pulses can create two rising edges inside vanilla's flight-toggle
window, toggling flight off; a bot that then re-enables flight can oscillate abilities as well as sprint.

While the automation owns altitude input and authorized flight is already active, prevent its synthetic pulses from
accumulating the manual flight-double-tap timer. For the checked versions, clearing the jump-trigger timer before
local-player input processing is one narrow implementation. Verify that the hook is installed in both load-time and
attach builds. Preserve ordinary manual double-jump behavior outside the bot's ownership. Do not spoof `mayfly`, write
velocity or add movement packets to compensate for a missing hook.

## Enclosure, routes and layer completion

- Flood-fill a fully loaded bedrock/unbreakable outline from a stable **interior** seed. Resurvey from that seed;
  using the player's latest cell after touching a wall can misclassify an enclosed mine as outside/open.
- Treat ladders and similar permanent fixtures separately from ore and air. Exclude fixtures from mining work and
  floor/reset detection while retaining their real collision shapes.
- Keep layer completion independent of the currently aimed block. The miner can break any selected, visible,
  reachable instant block above/below the reference layer. Descend only after the whole footprint is observed clear
  across repeated fully loaded surveys. Ignored, protected, fluid or unknown cells must not silently count as cleared.
- Keep one floor reference so clearing a nearby hole does not lower hover height. Predict vertical coasting and
  retain floor/headroom clearance. After full-layer confirmation, descend promptly through valid normal input.
- Favor longer passes when geometry permits; track recent routes to avoid retracing the same line. Mine continuously
  with held vanilla attack on genuinely instant blocks, but commit sensibly when a block needs multiple ticks.
- Plan a continuation before reaching the wall. Curve tangentially into it using actual progress and a short
  speed-dependent lookahead. Distant wall detection should queue a plan, not immediately brake in the middle of the
  mine. Keep turn speed/acceleration bounded and blend back into mining aim after the corner.
- Wall contact and crossing the navigation inset are not equivalent to leaving the mine. If the body is outside,
  suspend attack and plan a loaded, collision-free inward route. A lift/cross/lower recovery over a wall needs verified
  headroom and a valid return height. Settle safely inside before resuming; pause if the route is unknown or blocked.

## Distinguish diagnostics from a server check

A local “Self-Flag” message is a client heuristic. More than one action packet in a tick is not inherently invalid:
vanilla can abort an old mining target and start a new one in the same call. Classify the current version's actual
attack packet, count a dispatched packet once rather than counting queue+replay, and report the observed sequence
without inventing an anticheat verdict. If the user cannot see check names, inspect available local evidence and
state what it establishes; absence of a named check is not evidence of acceptance.

Useful probes include one start across hundreds of safe turning/altitude ticks; immediate release for unsafe input;
rejected starts and cooldowns; manual sprint adoption; repeated query idempotence; ladder-side walls; concave corners;
outside recovery; modified flying speed; focus loss; and real-version transformation of both sprint and altitude hooks.
Separate simulation, bytecode verification, live movement traces and server-specific acceptance in reports.
