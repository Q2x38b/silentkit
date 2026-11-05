---
name: silentkit-modules
description: >-
  Engineering reference for the module/method layer of a ghost client: the module/event/setting architecture,
  a shared humanization engine (eased rotation, mouse-GCD quantization, timing realism), silent-aim with rotation-
  ownership arbitration, vanilla-physics prediction (fall / flight / projectile sims), aim-control math (PD+I,
  leading), and the combat/world technique patterns. Use when designing or extending modules, or starting a client
  from scratch. Brand-neutral and framework-agnostic; pair with the queryable database at references/modules.json.
---

# Modules and methods

A build reference for the behaviour layer of a ghost client. It is deliberately brand-neutral: it describes
*patterns and math*, not any one project's code. API names are illustrative (modern Minecraft-style), but the ideas
port to any game/engine with a tick loop, an input pipeline, and an outgoing-packet path.

The companion file `references/modules.json` is a structured catalogue of every module and technique below — query it
instead of re-reading prose when you need "which modules exist / what does X do / what signals does Y use."

**Evidence rule of thumb.** Numerical examples and bypass ideas need version/server-specific validation. Separate
implemented fixes, source-confirmed pitfalls, simulation results and live observations. A local Self-Flag warning is
a client diagnostic, not a server verdict; a clean trace or read-only feature is not a guarantee of acceptance.

General module engineering lives in this document; query `references/modules.json` for per-module contracts,
aliases, settings and concrete `bypass_tips`. The one detailed detection/bypass reference is
[anticheat bypass and validation](references/anticheat-bypass.md). Read it for action validation, detector-facing
constraints and experiments; no numerical example here is a universal server threshold.

The server observes the protocol stream together with its authoritative world, permissions, plugins and timing.
Trace the final dispatched action, not merely a desired camera angle or a locally predicted result. Rendering-only
features should add no gameplay traffic; audit optional commands, input changes and external-service calls separately.

---

## 1. Module / event / setting architecture

- **Module base** — lifecycle hooks (`onEnable` / `onDisable` / `onTick` / `onKeyPressed` / `onWorldLeave`), a
  `Category`, a keybind, and a `setting(...)` registration helper that returns the setting so fields initialise inline.
  A `WorldOverlay` interface (`renderOverlay(Render2D, partialTick)`) and a `HudModule` subtype layer rendering on top.
  One central registry (`registerAll`) constructs every module; a filtered registry can drop modules whose hooks are
  unavailable in a given build (e.g. mixin-only modules in an agent-less injected mode).
- **Settings** — typed descriptors: `Bool`, `Number` (min/max/step/unit), `Range` (a low–high pair that draws a random
  value in-band), `Mode` (enum), `Color`, `String`, `Keybind`, `Action` (a button), `ItemList`, `Target`, and a
  `Section`/`Tabbed`/`Popout` group. Every setting supports `.visibleWhen(predicate)` for conditional rows and
  `.legacyKeys("old_id")` so saved configs survive renames. `onChange(runnable)` lets a module reset state when a mode
  flips. A **`TargetSetting`** is worth calling out: it bundles *entity types* (players / mobs / animals / …) with
  *filters* (ignore invisible / friends / teammates / bots) into one reusable "is this a valid target" test — combat
  modules share it so target policy is set once and obeyed everywhere.
- **Tick timing matters.** Drive the *decision* (target, whether to attack/place) at end-of-client-tick, where a
  rotation you set is what the *next* physics step and the *next* outgoing move-packet both consume. Do per-frame work
  (smooth aim, click scheduling above 20 CPS, render) off a render hook with a real `dt`, so motion and timing aren't a
  20 Hz staircase. Aura is the canonical split: **targeting/attack decision on tick, the actual turn every frame.**

**Scaling patterns worth adopting:**
- *Single reified event object* — one mutable struct with an int `type` and a union of fields; modules opt in with
  `listens(type)` and may mutate the event (cancel, override a query, rewrite rotation). Cheaper and more flexible than
  many listener interfaces once the event surface is large.
- *Data-driven setting catalogue* — load settings + descriptions from a JSON catalogue and fetch typed values by key,
  so module code carries almost no setting boilerplate. Worth it past ~100 modules.
- *Batched, vetoable enable/disable* — queue toggles, apply two-phase (mark-all then notify-all) so a mid-tick toggle
  never corrupts iteration; let a disable be cancelled by a hook.
- *Shared blackboards* — tiny static mediators between modules that would otherwise fight: a `CombatState`
  ("AutoCrit is working a target, WTap stand down"), a `PacketConflicts` helper that auto-disables a module already
  holding a shared rule slot before the newcomer claims it. Cheaper than event plumbing for a handful of known clashes.
- *First-class notification/toast queue* — a shared surface for alerts, module-toggle feedback, and update notices.
- *Scoped actions and transactional enable* — bind deferred work to owner/player/world/menu identity, recheck each
  individual click and cancel on disable/session change. Roll back failed initialization, release only still-owned
  hotbar selections, and coordinate shared option baselines. See the ownership and transaction rules below.

### Ownership, cancellation and independent features

- Bind work to `{owner, player, world/session generation, prerequisites, deadline}`. Module re-enable creates a new
  engagement. A surviving connection, UUID or menu title does not preserve an old task's authority.
- Enable transactionally: roll back partially acquired keys, timers and claims if setup fails. Bound consecutive
  tick failures, reset the error count after success and disable cleanly instead of retaining controls indefinitely.
- Camera, movement, attack, item use, hotbar selection and packet rules are separate resources. Recheck the actual
  claim before each action; distinct independently cancellable tasks need distinct owner tokens.
- A temporary slot swap is a lease: restore only in the same session while still owning the expected selection.
  Manual slot changes revoke restoration. Shared option overrides need one baseline, prioritized claims and a way
  to preserve user edits; independent snapshots restore the wrong intermediate value in different disable orders.
- Keep separable features independently configurable: navigation, economic/menu actions, destructive cleanup and
  combat are different tasks. Migrate old combined settings only when the new explicit keys are absent.
- A readiness announcement and an active timed effect have different lifetimes. Keep unused availability pending
  through menus or another owned task when the server semantics permit it; start the effect deadline on activation
  or confirmation, not on message receipt. Death/session replacement/disable invalidates pending work. Interrupting
  an already consumed effect must not queue a second activation. Report detected, deferred, attempted, confirmed and
  failed states separately so a missing action is not misdiagnosed as missing chat detection.
- Observe server announcements at a verified incoming-message hook on the game thread, independently of display
  filters, line wrapping and action-bar rendering. Separate server notices, attributed player chat and local echoes;
  normalize formatting/spacing and test captured messages. Do not replay historical chat when a module is enabled.

---

## 2. The humanization engine

The shared realism layer. Prefer common time, ownership and output contracts over independent ad-hoc controllers;
a shared statistical fingerprint alone does not establish lower detectability.

**Primitives (`Human`, stateless, thread-safe via a thread-local RNG):**
- `range(min,max)`, `gaussian(mean,sd[,clamp])`, `jitter(spread)` (gaussian around 0), `chance(percent)`.
- `logNormal(sigma,min,max)` — a right-skewed multiplier centred on 1 (`clamp(exp(N(0,sigma)),min,max)`). Use it for
  per-tick turn pace and any "speed/interval" that a symmetric uniform or gaussian would make too even (both are tells).
- `reactionMs(min,max)` — a **triangular** draw (average of two uniforms), mid-biased, so most reactions cluster and
  the extremes are rare. A flat uniform reaction time is itself a tell.
- `smoothstep(x)` — Hermite `x·x·(3−2x)` ease for ramps.
- `approach(cur,target,rate,dt)` — one step of a **frame-rate-independent** exponential approach, moving
  `1 − e^(−rate·dt)` of the remaining distance. Use this everywhere instead of `cur += (target−cur)·k`, which is
  framerate-dependent and so leaks your FPS into the rotation signal.
- Stateful noise also needs a time base: for a stationary AR process, use `a = exp(-dt/tau)` and scale innovation
  by `sigma * sqrt(1-a*a)`. A fixed per-tick coefficient is an example at that cadence, not a per-frame constant.
- `mouseGcd()` and `snapToGrid(base,target,gcd)` — the GCD rule (below).

**Reaction gate (`Reaction`, stateful).** `ready(present, minMs, maxMs)`: arms a randomized delay on the *rising edge*
of a stimulus and returns true only once it elapses, then holds true while the stimulus holds; drops back to waiting
when it goes away, so each fresh appearance costs a fresh reaction. This is how "don't act on the same frame the target
appears" is implemented uniformly.

**Eased rotator (`HumanAim`, stateful).** The rotation arm of the engine; each aiming module owns one and `reset()`s it
when it stops aiming. One `advance()` per tick (or frame) produces a step with, in order:
- **Hand drift** — an AR(1)-smoothed low-frequency micro-wander (`drift = drift·0.92 + jitter(0.04)`), amplitude a
  tenth of a degree, added to the target. A rotation that sits *perfectly frozen* on a moving target is flaggable; this
  keeps it alive without ever costing a hit (far inside the hitbox).
- **Ease-in ramp** over the first ~3 ticks (`min(1, 0.4 + ticks·0.2)`).
- **Exponential approach** of the remaining delta (`frac = 1 − e^(−speed/28)`).
- **Ease-out settle** with a *firm floor* (`clamp(|delta|/12, 0.34, 1)`) so the last couple of degrees close in a tick
  or two instead of floating forever — smooth *and* snappy.
- **Per-tick pace — a right-skewed log-normal**, `pace = clamp(exp(N(0,0.14)), 0.72, 1.6)` (median 1), so the turn
  never advances the exact same fraction twice. This replaces the old symmetric uniform `×[0.85,1.15]` band: real human
  turn speeds are right-skewed (most a touch slow, the odd fast one), and a flat band reads as too even to a detector.
  Optional positional jitter while turning (`jitter(0.12)` on yaw, `0.08` on pitch) above 1.5° of remaining delta.
- **Overshoot** — a turn over ~25° flicks `min(|delta|·0.12, 6)°` past the target, then the offset decays (`×0.55`/tick)
  and the normal pull settles back. Rate-limited (~500 ms) so it isn't on every micro-correction.
- **Flick guard** — a hard `±70°/tick` ceiling: no matter how high aim speed is set, never turn more in one tick than a
  hand plausibly could.
- **Whole-count emission** for both server-path and camera contributions (see the correction below).

Two entry points: `camera(...)` eases from the *live* camera (so your own mouse still counts and the view interpolates
smoothly) and `silent(...)` seeds from itself/the camera, for the server rotation. **Both must put the rotation the
server sees on the grid** — see the correction in rule 5 below; a camera aim-assist whose rotations reach the server is
*not* exempt.

**The mouse-GCD rule (the key anti-detection realism).** A real mouse turns only in whole "counts," so every rotation
the vanilla client sends is a multiple of a sensitivity-derived step. The engine mirrors the exact vanilla math:
`f = sens·0.6 + 0.2`, then `gcd = f³ · 1.2` **degrees per count**. A detector that reconstructs this GCD in an aim-analysis pipeline flags any rotation delta not on the grid. Rules:
1. Snap the rotation that goes *on the wire* to the grid, anchored on the last sent value:
   `snapped = base + round((target−base)/gcd)·gcd`.
2. If a snapped step rounds to 0 but the target is still ≥1 count away, take the smallest grid step that *progresses*
   (`sign(delta)·gcd`) — never stall short of a reachable target.
3. **Carry the sub-count remainder** across ticks instead of snapping-and-dropping it — a real mouse accumulates.
4. Advance eased aim on a real `dt` time base (sub-tick) so the yaw-rate signal isn't a 20 Hz staircase; snap only the
   value that actually leaves on a packet.
5. **A camera aim-assist is not exempt from the output contract.** If the module turns the real view and those rotations
   reach the server, apply them as **whole mouse counts** too — convert the degree step to counts (`step/gcd`), add the
   carried remainder, **truncate to a whole count**, apply `count·gcd`, keep the fraction. Done through the mouse-input
   path, validate visible smoothness and the serialized deltas across sensitivities and frame rates; the shared
   contract prevents a raw contributor from defeating the quantized ones.

**Controller troubleshooting:** apply speed/acceleration and disabled-axis constraints to the final output after
every noise/feed-forward term, and keep candidate points inside the actual hitbox. Keep camera momentum separate
from target-motion estimation: reset samples on identity changes, teleports or meaningful tracking gaps instead of
differentiating across unrelated targets. Use `alpha = 1-exp(-dt/tau)` and
scale stochastic decay/innovation with elapsed time. Preserve momentum through ordinary retargets, but clear stale
velocity and fractional counts after ownership changes or long stalls. Revalidate one cached target per frame;
replace it only when invalid or a competitor improves materially. Use entry/exit hysteresis around an on-target zone.
Audit private RNG paths when a global humanization level is exposed; adding independent noise does not repair a
state/time bug. Detector-facing checks and the frame-rate matrix are in
[anticheat bypass and validation](references/anticheat-bypass.md#rotation-output).

**Rotation-stream calibration examples (verify on the target implementation):**
- **Measure variation at the protocol's sampling cadence.** Per-frame noise can average out within a protocol tick,
  while a rate cap can dominate the result when tracking a fast target. If experimenting with a varying response,
  update its envelope at a measured cadence and ease toward it. Compare final sampled output with the relevant
  baseline instead of assuming a particular multiplier or re-roll interval is a bypass.
- **One off-contract contributor can invalidate a shared output.** An auto-clicker's independent fractional
  `turn()` jitter can reintroduce deltas excluded by an otherwise quantized aim controller. Every view contributor
  (click jitter, aura, clutch, scaffold, recoil) needs the same output contract or one shared applier. Test modules
  separately and together to distinguish an individual fault from a conflict between contributors.

---

## 3. Silent aim + rotation-ownership arbitration

Silent aim sends a server-only rotation while the camera stays put. **Transport:** at the outgoing move-packet site,
swap the camera's yaw/pitch for the aim rotation (grid-snapped), let the packet serialize, restore after. Snapshot the
previous tick's rotation once per tick so a render hook can interpolate the server rotation between ticks (for a 3rd-
person head that points where you aim, and an aim-indicator line) without a 20 Hz step.

**Two rotations, two packet paths — the subtle bug.** The move packet carries one rotation, but a *use-item / interact*
packet carries its **own** yaw/pitch. So a silent-aimed throw/place will fire where the **camera** points unless you
also feed the silent rotation into the use path for the duration of that one interaction (a `useWithSilent` flag the
use-packet hook reads). Symptom when you forget: "upward pearl didn't go up," "wind charge flew at the camera." Compute
ray-trace / reach against the silent rotation too, not just the move packet.

**Rotation-ownership claim — the pattern that prevents two modules fighting.** Many systems want the rotation (combat
aura, crystal/anchor placement, scaffold, clutch, pearl, wind charge, fireball deflect…). A single last-writer-wins
owner causes two real bugs: placement modules flickering the rotation between targets, and one module's release
cancelling another's in-progress hold. Fix with a claim keyed on an **owner token**:
- `aim(yaw, pitch, dist, ownerToken, correctMovement)` — a different owner that refreshed recently (within ~120 ms /
  ~2 ticks) **keeps** the claim unless the newcomer has strictly higher `priority(token)`. A stale claim (owner stopped
  refreshing) is free to take. Priority order in practice: **life-saving clutch (100) > combat aura (50) > placing (20)**.
- `release(ownerToken)` is a **no-op unless that token holds it**, so a module disabling can never cancel another's
  hold.
- On release, don't snap: ease the server rotation back to the live camera over a fraction of a second (exponential
  approach with a speed cap, ~¼ s for a 90° swing), then stop sending it.

This is the same single-owner claim idea used for shared packet rule-slots (§6) and the hotbar/action lock —
generalise it into a shared `ControlClaim { owner, priority, lastRefresh }` reused anywhere two modules might contend
for one resource. `correctMovement=false` is passed by placements and throws (their near-straight-down yaw says nothing
about where you mean to walk).

**Movement correction** — when the silent rotation diverges from your camera and you're walking, re-pick WASD against
the *server* yaw so what the server simulates matches the rotation it has:
- *Proper*: project your steer direction onto the server facing, snap to the nearest of 8 directions, rewrite the key
  booleans and the move vector, and **sprint only when that direction is forward** of the server facing (a backward
  sprint is impossible and flaggable).
- *Slow*: keep your real keys, but kill sprint whenever you're steering more than 45° off the server facing.
- *None*: leave movement alone (correct for throws/deflects, where steering your walk would be wrong).

**Act on the rotation you actually SEND, not the one you're easing toward — the consistency rule.** A module that
decides "am I on target / is this placement reachable?" against its *desired* aim point, but fires the action on the
tick the server only sees the still-easing rotation, acts inconsistently with its own state: the aura hits where it
isn't looking, the clutch places against a face it isn't pointing at. Gate every server action (attack, place,
interact) on the rotation that is/will be on the outgoing packet this tick — the transport's current `yaw()/pitch()` —
not the target you want. With a slow aim speed the desired-vs-sent gap is wide, so it matters most there. For a
life-or-death placement (clutch), prefer **rotate-first**: aim at the face and only release the action once the sent
rotation lines up, with an emergency fallback right before the deadline. Anything replaying your sent rotation
otherwise sees the action land where you weren't looking.

**Keep the server rotation near the camera while you move.** The further the silent yaw swings from where you're
walking, the harder your motion is to reconcile *even with correction on*. Cap the aim's field of view (≈55°) and
track fast enough that the sent rotation doesn't lag far behind the target — small divergence + correction reconciles
cleanly; a wild divergence doesn't, correction or not (correction *off* is the worst case of all).

---

## 4. Prediction systems (vanilla-physics sims)

The highest-leverage pattern: **simulate the game forward and act on where things will be.** The anticheat can't object
— your resulting packets are legal; you simply computed the right one. General recipe: build an AABB from a start
pos + velocity, loop ticks applying the entity's real accel/drag, resolve collision **per axis** against the world's
collision shapes (`Shapes.collide` on Y, then X, then Z against the swept block shapes), read the world only (never
mutate entity state), cap the tick budget.

- **Fall simulation (clutch/MLG/mace).** Step vanilla fall physics — `vy = (vy − 0.08)·0.98`, horizontal air drag
  `·0.91` *only on an axis that didn't collide*, per-axis collision sweep — up to ~70 ticks (≈3.5 s, enough for terminal
  velocity to reach ground or the void). Return `{lands, voided, landX, landZ, drop, water}`. Because it simulates the
  **real arc from your current velocity**, it catches a knockback/momentum throw that carries you off *sideways*, not
  just a straight-down drop — and it hands placement the exact **column you'll land in**, so blocks go where you're
  actually going.
  - A clutch fires on three triggers judged off this sim: *stepping off an edge* (on ground, moving, not jumping,
    nothing under the next step, and the simulated fall from there is dangerous), *descending* (airborne, falling, sim
    is dangerous), and *staircasing* (jump again right after a clutch). "Dangerous" = voids / never settles / exceeds a
    block threshold / would exceed your health after safe-fall and fall-damage-multiplier attributes. Lands in water →
    never dangerous.
  - **Placement lead and confirmed support.** Predicted placement/landing can precede server acknowledgement.
    Plan against real reachable supports, validate the exact action ray, and account for latency before treating a
    new block as load-bearing. A* can search candidate support chains, but each step still needs live revalidation
    and observed confirmation. If no valid support chain exists, use another supported fall mitigation or stop;
    do not force a placement to satisfy the prediction. See [action validation](references/anticheat-bypass.md#reach-placement-and-mining).
  - **MLG/auto-bucket** can reuse the landing simulation and a reachable top-face ray, subject to the dimension's
    fluid rules, actual held item and server/world acknowledgement. Revalidate retrieval as a separate use action;
    predicted water, local landing and confirmed damage prevention are different observations.
  - **Mace fall-smash impact timing:** a smash does the most damage on the *last airborne tick*, so hold the attack
    while still falling and only release when `aboutToLand` — step one vanilla fall move ahead (`(vy−0.08)·0.98 − 0.08`)
    and check whether that move collides. A very large drop (>5) smashes immediately rather than risk clipping the
    ground a tick early.
- **Flight autopilot (self-contained, no pathing dependency).** Steer rotation toward a far target, pitch-control to a
  cruise altitude with a heightmap corridor scan ahead (climb over terrain), boost on a randomized cadence, grid-align
  the rotation. Principle: set only the *legit inputs* (rotation + boost item use) and let vanilla physics move you, so
  movement always matches look.
- **Projectile trajectory.** A step integrator for thrown items with the real per-type constants. For an ender pearl:
  `gravity 0.03`, `air drag 0.99`, `throw speed 1.5`, step `vel = vel·drag − (0,gravity,0)`, move with a per-step block
  clip, up to ~300 ticks. Two uses: (a) **predict an enemy projectile's landing** by seeding the sim with *its* current
  pos+velocity; (b) **solve your own launch** — brute-force the launch pitch (at the yaw toward the target) over a range
  (e.g. −75°…+35° at 1.5° steps), simulate each, keep the pitch whose landing is nearest, add your inherited horizontal
  velocity when airborne, and only throw if the best miss is within a tolerance. This is auto-pearl: land where the
  enemy lands. The same integrator draws trajectory lines and leads bow aim.

---

## 5. Aim-control math

Baseline (what a good aim-assist does every frame): exponential approach of positional error + reaction/reacquire
delay + ease-in + overshoot + drift + a multi-sine shake; lead the aim point by target motion. The reference aim
controller layers these in one `turn()`:

1. **Target-rate feed-forward.** A pure exponential ease can trail a strafing target by a roughly constant angle.
   Track target angular velocity with `alpha = 1-exp(-dt/tau)`, then `ffRate += alpha·(Δwant/dt-ffRate)`; a fixed
   0.6/0.4 per-frame blend has different physical response at different FPS. Reset samples on retarget/teleport and
   bound the final combined output, moving *with* the target instead of lagging it. (A full controller adds a
   leak-decayed **integral** bias and a **derivative** term for PD+I; feed-forward is the highest-impact piece and the
   one implemented here.) Clamp it so a retarget/teleport spike can't fling the aim.
2. **Velocity/distance-scaled leading.** Lead the aim point by the target's per-tick velocity scaled by distance (your
   turn takes longer to land at range): `leadTicks = clamp(dist/6, 1, 3)`, move the hitbox by `vel·leadTicks`, with a
   smoothed lead point and a lag clamp.
3. **Closest-point-on-hitbox** with eye-aligned Y: the point along your current look at the target's depth, pulled just
   inside a deflated hitbox — so "Closest" tracks the nearest surface and blends height when you/they jump.
4. **Richer noise.** A multi-octave sinusoidal shake (sum of sines at randomized phases/freqs, applied as the *delta*
   the wobble changed this frame so it's smooth), plus the drift-aim-point: wander toward a random spot inside the
   middle of the hitbox, reseeded every 400–700 ms, approached frame-rate-independently.
5. **Adaptive speed.** Quicker for big corrections, gentler near the target, softer still once the ray is *on* the
   hitbox (`scale = clamp(|Δyaw|/20, 0.35, 1.5)`, ×0.4 when on-target). Ramp 0→1 over an ease-time after acquisition.
6. **Per-target randomized gains** (×0.8–1.2) and **per-tick lognormal speed** with a point-blank slowdown, so each
   engagement has a different signature.

**Reaction / reacquire** are modelled distinctly: a brand-new target costs a triangular reaction delay; a target that
reappeared from behind a block within ~3 s costs a shorter *reacquire* delay and a forced ease-in (a human re-finds a
target that ducked behind cover faster than one they've never seen).

---

## 6. Timing realism (clicks + packets)

**Auto-clicker timing models.** A frame scheduler can resolve intervals between game ticks, but the actual action
path and protocol still constrain dispatch. The following rhythm/fatigue models are candidates to compare with a
relevant measured baseline; no distribution establishes human origin or server acceptance:
- **Lognormal (right-skewed) gaps:** `gap ·= exp(k·gaussian)` (k≈0.14). Most gaps near the mean, the odd long one,
  almost never an impossibly short one. A symmetric gaussian around the mean is itself a tell.
- **Repeat-gap tendency:** ~18% of the time, reuse the previous interval ±a few ms. Hands fall into a cadence; they
  don't re-roll every click.
- **Mean-reverting (Ornstein–Uhlenbeck) CPS walk** toward a target that drifts through the range and re-rolls
  occasionally, each gap getting its own spread around it — instead of an independent uniform draw per click.
- **Fatigue *and* bursts:** CPS jumps near the top of the range for the first ~1.5 s of a fight, then slides toward the
  bottom over a long trade (`0.15 + 0.75·e^(−(t−1.5)/12)`), with a slow random wander on top. Recovery between fights,
  not just monotonic decay.
- **Injected micro-pauses:** ~1.5% chance per click of an extra 50–150 ms, the kind a real player drops in.
- **Optional double-click rhythms.** Some devices/styles produce pairs; this is a configurable timing model, not a
  requirement that every real mouse double-clicks. If used, keep the second click subject to the same current target,
  charge, focus, ownership and input gates as the first; cancel it when those prerequisites fail. Preserve configured
  CPS meaning and measure consumed clicks instead of assuming scheduled clicks were all executed.
- **Modelled press→release hold window** per click — an instantaneous click has zero press-time variance, which is a
  tell on servers that see both edges.
- **Style rhythms** that still average to the CPS: *Jitter* (steady, spread from the lognormal), *Butterfly* (quick
  pairs then a longer gap), *Drag* (a fast run of 4–8 then a pause).
- **Charge gate (optional):** hold each click until the attack has recharged — `getAttackStrengthScale ≥ a per-click
  randomized 0.88–1.0` (re-rolled each click, capped at 1.0), retrying every frame — so you never click *through* the
  cooldown for a 0-knockback reset hit. More damage per swing, and the cadence naturally matches the weapon's cooldown.
- **Click Assist** amplifies *real* clicks (each genuine press fires a few extra 45–100 ms behind it) so nothing ever
  free-runs — the most defensible mode. **Range-aware** gating (only click with a valid target nearby) stops "clicking
  at the air." Stand down entirely while an aura is driving the attack, or you'll reset the cooldown it times hits on.

**Scheduling tip:** route primary, assist and pending second clicks through one final eligibility check. Use explicit
monotonic-clock units and clear work on mouse release, menus, disable or session replacement. Use `nowNanos + delayMs * 1_000_000L` when the scheduler clock is nanoseconds; a second cooldown can mask a units
bug, so test the actual deadline independently. Optional double-click rhythms are modes, not compulsory behavior.
Count generated, cancelled and consumed clicks separately and discard stall catch-up. The full dispatch contract is
in [click validation](references/anticheat-bypass.md#click-validation).

**Packet timing — one owner-aware queue** (full architecture — queues, re-entrancy, ordering, allowlist — in §11). A single `PacketDelay` service holds packets on the client's own connection
and replays them in order on the main thread. It exposes **owner-aware rule slots** (outgoing, incoming/knockback,
per-entity) claimed with a module token; a second claimant notices the clash and the conflicting module is auto-disabled
first. Refinements shared across FakeLag / Blink / KnockbackDelay / BackTrack:
- Cap a held packet's **age** (a Max-Desync setting, e.g. release once the server is >N ms behind where you really are)
  to bound retained state; the age cap is not an acceptance guarantee.
- **Allowlist what you delay.** Only *position* packets get held; block/item actions (which carry a client sequence the
  server acks and predicts against), container clicks, keep-alives, chat and teleport-confirms go out live — holding
  those desyncs blocks/inventory or times you out. When a live packet follows held ones, flush the held ones first so
  order is preserved.
- **Flush and pause** instantly on your own attack packet, on taking knockback, and on any server position-correction /
  teleport (track "last correction" on the network thread) — so it never fights the server.

---

## 7. Combat / world technique patterns

- **Crystal / anchor (obstruction-validated placement + a damage model).**
  - Compute **real explosion damage**: vanilla normalises distance by `radius·2` (power 6 → 12), a linear falloff
    `(1−d)` × **exposure** (fire a small grid of rays from across the target's hitbox back to the blast centre; the
    fraction unobstructed is the seen-percent), then `((imp²+imp)/2·7·q+1)`, reduced by armour+toughness, blast/generic
    protection (blast counts double), and Resistance. Rank candidate bases by damage-to-target.
  - **Always validate placement reachability with a raytrace** — eye→face clip must land on the candidate block (or
    nothing between), or the server rejects the placement. This is what stops placing "into a wall / on fire": a legit
    place needs a **full, sturdy face** to click (not a slab/fence/torch/replaceable), and the clicked face must be in
    reach and unobstructed. The identical check drives a "can I place here at all" predicate so an aim-view releases the
    camera when nothing's placeable.
  - **Anti-suicide** gates every place *and* detonation: estimate the **self-damage** with the same explosion model keyed
    on your own eye (distance falloff over `radius·2`, a line-of-sight exposure term — a clear ray ≈ full, a blocked one
    ≈ `0.45`, deliberately conservative so it errs toward *not* blowing yourself up — then the vanilla armour reduction)
    and refuse if it would kill you (`≥ health + absorption`) or exceed a max-self cap; pause all self-damaging actions
    while you're actively shield-blocking. AutoAnchor uses exactly this at `radius 5` before every detonation.
  - **Min Target Damage** threshold (on top of the self-vs-target scoring, the anti-suicide/max-self gate and exposure
    efficiency): skip any placement or detonation whose estimated *target* damage is ≤ 0 or below a minimum, so weak
    trades don't waste crystals.
  - **Predict:** lead the target by a short forward sim / its velocity for both the damage ranking and the detonate aim;
    **rapid-fire:** place-and-break in the same tick above a min-efficiency; **client-remove** the detonated crystal so
    the next place fires immediately. Interactions carry explicit coordinates, so the aim and reach must agree with the chosen interaction and the actual sent rotation.
  - **Respawn-anchor combo** is a staged state machine (PLACE → [COVER] → CHARGE → DETONATE → POST), each step paced by
    a tick timer, *confirmed against the world* (anchor present before charging, charge risen before detonating), and
    retried a few ticks before giving up. Dimension-gated (anchors set spawn, not explode, in the Nether). Carries the
    same reachable-face raytrace and silent-aim handling.
- **Block placement (scaffold / clutch / surround / auto-ladder) over a shared service.**
  - The shared placer fills a target by **clicking a sturdy neighbour's exposed face** the way a right-click would, with
    the reach + sturdy-full-face check centralised, and reports the exact hit point back **only on a successful place**
    (so a failed reach never turns your head). `blocksNeeded()` returns 0/1/2/−1 (solid / has a neighbour / needs a
    diagonal step first / impossible). `support()` only accepts a neighbour whose face is `isFaceSturdy` and not
    replaceable — a slab / fence / torch / carpet / air / water / fire is rejected *before* a packet goes out, which is
    what prevents the "placing into air / on fire" rejected-packet bug.
  - **Hit-vec jitter.** The clicked point is the neighbour face's centre plus `jitter(0.18)` (clamped `±0.4`) on the two
    **in-plane** axes only — never along the face normal — kept well inside the face so the block still places and stays
    in reach. Without it every placement lands dead-centre on the face, a trivial tell. The planner and executor must share the same sampled point; a readiness ray to a different center does not validate it.
  - **A shared A\* placement planner** (`PlacementSearch`), as an implementation pattern. `frontier(targets)`
    returns the subset fillable *this tick* (replaceable *and* a reachable sturdy face exists), ordered **cheapest aim-
    movement first** (`rotCost = |Δyaw| + |Δpitch|` from your current look to the click face), so a caller places one or
    a few per tick with the smallest turn and the frontier re-expands next tick as fresh blocks create new supports.
    `planTo(goal, maxSteps)` is a **bounded best-first (A\*)** over the 6-neighbourhood to bridge to a goal you can't
    reach yet: seed the open set with every placeable-now cell near the goal, treat each expanded cell as solid-once-
    placed, order by `path.length + blockDistance(goal)` (cost = steps, admissible heuristic), prune past reach/budget,
    and return the placement order ending at the goal. A surround caller can run on `frontier()`; scaffold, clutch and
    auto-ladder can share the same solver with different goal tests — "which block next" becomes one planner.
  - **Scaffold** modes: *Legit* (predictive auto-sneak at edges — crouch when a fixed look-ahead along your heading puts
    your feet over air, released on a randomized human hold; you place), *GodBridge* / *TellyBridge* (places under your
    feet as you walk / only while airborne, diagonals included, never above start-Y + a Y-increase). Key correctness
    bits: **half-block-aware placement Y** (feet at `.5` on a slab → build from `floor(y)`, else `floor(y)−1`), a
    nearest-first ring of feet spots (next-tick landing, diagonal corner-fills, current column), and an **Expand
    re-anchor** — if the feet column can't be filled (you clipped a corner / stepped a gap), reach out to the 8
    neighbouring columns so you catch yourself instead of falling.
  - **Clutch** scans from just under the feet downward through reach, trying the whole 3×3 ring plus the momentum/landing
    column nearest-first, places at the highest reachable support, then returns owned slot/view claims. Ease the view
    and validate the actual action rotation and hit candidate before use. A `released()` check (landed, no longer in
    danger, timed out or cancelled) prevents a stale rotation claim after the action ends.
- **Enchant-weighted item scoring.** A shared comparator so auto-armour, auto-weapon, "best-gear-only" chest-steal and
  the inventory manager all agree: score armour as armour points + toughness (half-weighted) + protection; a weapon by
  attack damage + small per-enchant bonuses; a tool by dig speed + efficiency/fortune. Driving it off the item's own
  **attribute modifiers** keeps it robust across game versions (higher is always better). Feeds a best-per-slot equip +
  a 2-set quick-swap, and a "better than what's equipped" gate for looting.
- **Anti-bot behavioural score.** Combine independent received cues instead of promoting invisible, stationary or
  unlisted status directly to certainty. Hovering can have legitimate causes; account for abilities, fluids, riding,
  effects and incomplete observations. Calibrate confidence/expiry for the target environment and cache the result
  once per tick for shared combat/visual consumers. Team identity is strongest when actually supplied by the game's
  team state; matching name colors or prefixes are weaker configurable hints, not universal teammate proof.
- **BackTrack (opportunistic rewind for reach).** After you hit a target who then backs away, **hold just that entity's
  movement packets** for up to a Latency (its real server position keeps being tracked meanwhile, so it stays correct);
  on your screen it lingers where it was — closer to you — buying reach. It arms only once they start moving *away*,
  and the crucial gate: **only keep holding while the frozen ghost is still reachable and roughly in front of your
  crosshair** (eye-ray-to-hitbox distance ≤ reach, dot with view > 0.5). The moment it isn't — or you take knockback
  (your own position jumped), or they stop backing off for a couple of ticks — flush and let go, because holding past
  that just piles on flaggable desync. **The aim-ray dot gate is now the core test, not a refinement:** each tick,
  compare how on-crosshair the frozen ghost is (`ghostAim = look·normalize(eye→ghost)`) against where the target *really*
  is now (`realAim = look·normalize(eye→serverPos)`); keep holding only while `ghostAim > realAim` — the freeze sits
  *further along your look vector* than the live position, so it actually buys the hit. The instant `realAim ≥ ghostAim`,
  release: holding then only adds desync for no reach gained.
- **Hitbox assistance and real geometry.** When you widen a target's hitbox for easier hits, **project the outgoing
  interaction vector back onto the real box edge** then recheck the actual eye ray and reach against that real box. Projecting a point alone cannot validate an
  interaction the actual sent rotation would miss.
- **Range-gated exploits.** Only engage fakelag/timer/kb-delay when an enemy is within N blocks and roughly ahead,
  via a shared "nearest-enemy-within(range, angle)" predicate — so you're never desynced or lagging out of combat where
  it's both pointless and conspicuous. Dynamic fakelag goes further: lag while *closing* on a target, then dump the
  whole backlog at reach so you arrive and hit before they react; Repel lags only while your own movement vector points
  *toward* the target, keeping the server's copy of you as far from them as possible.
- **Bed-breaker.** Derive both bed halves from facing, build the first-layer cover positions, simulate every hotbar tool
  against every cover block to pick the fastest (cover, tool) pair, phased break.

- **Auto-mace enchant pick (by computed smash damage).** When several maces are in the hotbar, pick the one with the
  highest *expected* smash damage against the target at the current fall distance `f`, rather than a fixed Density-vs-
  Breach threshold. Vanilla fall-bonus curve `fallBonus = f≤3 ? 4f : f≤8 ? 12+2(f−3) : 22+(f−8)`; `raw = 7(base) +
  fallBonus + 0.5·DensityLvl·f`; Breach cuts effective armour by `0.15·lvl` (`armor = armorValue·(1−0.15·breach)`);
  reduce by the vanilla armour formula `cut = min(20, max(armor/5, armor − raw/(2+toughness/4)))/25`; `expected =
  raw·(1−cut)`. A big fall then favours Density even on an armoured target, where a fixed threshold mis-picks.
- **Velocity modification experiments.** Partial or probabilistic changes still alter a server-issued impulse.
  Record the original push, applied result and collisions, and test separately from normal knockback. Precision
  jitter changes a distribution; it does not restore the trajectory a prediction check expects.

**Modules that round out a modern kit:** aura (killaura / silent-aura), crystal / anchor, auto-mace with impact-timed
rotation + enchant-by-damage pick (folded into a trigger/auto-clicker + a weapon-swap), velocity / anti-knockback
(precision-jittered), knockback-delay, no-slow (a
`modifyInput` redirect that skips just the item-use slowdown scale), step (a transient `STEP_HEIGHT` attribute
modifier, ground-gated), auto-block (drives the real use-key to hold an offhand shield between your hits, dropped while
you attack), auto-pearl, pearl-catch / wind-charge jumps, scaffold, clutch, surround (feet-walling via the shared
placement planner), MLG / auto-bucket, auto-armor, inventory
manager / cleaner, backtrack (aim-ray-gated), fake-lag, blink, anti-bot (+ teammate detection), combat-predictor (per-player action classification +
next-move prediction + bearing, read-only), trajectories / ESP / chams, radar, a macro system, a base-finder, and a
notification / toast system. See `references/modules.json` for the full catalogue with per-module technique, hook,
anticheat-notes and settings.

**Three more techniques worth knowing (added from live work):**
- **Knockback steering ("hit-flick").** A sprint-hit's bonus knockback is applied in the *attacker's facing*
  direction, so turning the server-side yaw a few degrees off the target at the hit sends the victim off at that angle
  (alternate left/right to keep them in combo range, or drive them toward a ledge). Keep the pitch on-target so reach/
  raytrace stays valid. It's inherently flag-prone — a large or every-hit flick fails a strict "looking at target"
  check — so make it defensible the way anti-knockback is: a **Chance** gate (flick only some hits), a **small angle**,
  a **1-tick window** (only the hit's own movement packet carries the flick), and ideally a **packet-choke** (hold
  outgoing movement during the flick, flush right after the attack) so the server sees a controlled sequence rather
  than a sustained off-target look.
- **Ping-adaptive timing (the honest version).** Everything that sits behind the server — packet delays, backtrack,
  attack freshness — has a safe budget of `lag-comp-window − your ping` (windows cluster ~150–200 ms). A shared
  **network-conditions monitor** (smoothed ping + jitter + a spike flag, read from the keep-alive/transaction RTT) lets
  those modules self-cap to that budget and **back off on a spike**, instead of fixed delays that are fine at 30 ms and
  suicidal at 200 ms. It only *measures* latency; never fake it (inconsistent timing is what the timer check catches).
- **Client-side cheat detection (analysis, not a cheat).** You can score *other* players from the data you legitimately
  receive — their position stream and head rotation — with the same signals the server ACs use: sustained over-vanilla
  speed, airborne-with-no-gravity, inhuman instant head-turns, near-zero turn-speed variance. Decay the score so a flag
  means a sustained pattern, and keep thresholds conservative for accuracy. A clean way to reuse everything you learned
  building bypasses, pointed the other direction.
- **Break-automation (an auto-miner/nuker that holds up).** Automate block-breaking by steering the REAL view at the
  target and holding the attack key — let the engine process normal mining rather than sending extra break packets.
  Consistent input is a useful starting point, not a guarantee of server acceptance:
  1. **Drive the camera PER FRAME, not per tick.** The game breaks whatever the *render-interpolated* crosshair hits
     (recomputed each frame) while the server only sees the *per-tick* rotation — a per-tick jump desyncs them →
     "invalid break (X, looking at Y)" + abort/start double block-actions. Move it as whole mouse-counts through the
     shared applier (§2).
  2. **Commit sensibly on slow blocks.** Vanilla can switch mid-break and emit ABORT(old)+START(new) in one tick;
     that pair alone is not proof of a violation. Repeated unnecessary switches waste progress. For genuinely
     instant-break blocks, continuous held mining can sweep between valid reachable faces without per-block pauses.
  3. **Gate the break on a "not flicking" check** — only hold attack while the per-tick rotation is small (render ≈
     server), so a smooth continuous sweep breaks freely but a big flick waits a tick. Hold the key through the brief
     gaps so it reads as a continuous hold, not a per-block click.
  4. **Resolve occluders** — raytrace to the target; if a block is in the way, break THAT first instead of staring at
     the one behind it.
  5. **Give up on blocks that won't break** — a time budget + a re-commit counter blacklist region-protected blocks,
     else you grind a server-replaced block forever.
  6. **Separate ground and authorized-flight policy.** Do not blindly cancel sprint because mining or turning is
     active. In checked modern flight versions, a tapped sprint stays latched through forward+strafe and altitude
     input while the final forward impulse remains valid. Predict boosted body clearance and release for genuine
     braking/unsafe input. Keep ground hops, body collisions and fixtures governed by their actual version's physics.

### Stateful inventory and menu automation

Bind each click plan to the screen instance, container instance/ID, player and world. Same title/new ID is a new
transaction. Revalidate source, destination and cursor before every actual click, including each step of a swap;
budget actual interactions rather than queued lambdas. Match actions by normalized display text plus layout/material
information. Opening, transferring, requesting a transaction and observing its result are separate phases.

If quick-move is rejected, an explicit pickup/place sequence can help, with acknowledgement-aware progress,
partial-stack handling, rejected-slot detection and bounded retries. Inspect whether an item already moved before
retrying, or the retry may pull it back out. Transition to confirmation only with the intended contents and an empty
cursor. Scope destructive cleanup to explicitly chosen item groups/slots; spare hotbar/inventory armor does not
include equipped armor or offhand by default. Close only a menu the task still owns.

For dependent placement, retain one immutable `{target, support, face, hitPoint}` candidate from planning through
alignment and use. Sample an optional point once. Recheck the real ray, reach, replaceability, item and ownership
before execution, try other valid neighbors, and distinguish an interaction being consumed from a confirmed block
change. A full-face requirement is a conservative policy, not a universal placement rule. Emergency waiting starts
with the current attempt, not an uninitialized last-success timestamp.

### Navigation and multi-stage tasks

Use observed transitions such as `select goal → route → approach → settle view → act → observe result → recover`.
Route completion must describe the whole goal, not the first successful jump/platform. Replan on geometry, effects,
permission or target changes; normalize transient modifiers when comparing physics profiles so ordinary sprint
changes do not invalidate every route. Model ladders, vines, fluids, bounce blocks and other special transitions as
separate verified edges, not as universal jumps. Reject unsupported transitions explicitly.

- Prefer a stable interior survey seed over the player's current boundary cell. Unknown/unloaded, protected or
  excluded cells are not completed work. Permanent fixtures can be excluded as targets while retaining collision.
- Confirm whole-region/layer completion across loaded surveys before changing reference height. Maintain a stable
  floor/anchor, account for coasting/headroom, and distinguish wall contact from genuinely leaving the route volume.
- Use supported, player-width corridors and real step/jump limits. Water proximity alone does not establish a safe
  interaction stance or clear cast. Ease from route view into action view before the action starts.
- Choose the movement medium deliberately. A combat route through connected open water must not trigger the
  accidental-water escape policy. Float while holding melee position; aim only with actual reach and line of sight.
  Follow route waypoints while approaching, release target tracking on route failure and bound no-progress retries.
  Replanning should preserve camera acceleration rather than restart its turn every few ticks. Return via a
  climbable bank when the task ends; a two-block wall is not an exit and repeated jumping is not progress.
- Economic/navigation loops should pause casting before walking, account for any outstanding item/projectile,
  use a capacity hysteresis band, and observe transfers/sales rather than assume fixed sleeps mean completion.
  Navigation, selling, optional cleanup and creature combat can have independent switches. Without navigation,
  preserve the manual anchor/view for return; with it, reconsider nearby reachable goals from the current position.
- Inventory movement needs an explicit supported-screen policy and must reject focused text entry. Background
  operation is owner-specific: exempt only the active task's focus/held-input gates while keeping user-opened menus
  meaningful. Use elapsed time under FPS throttling and a bounded frame floor respecting the user's limit; do not
  rewrite a global pause preference just to keep one task running.

Exercise same-title/new-container IDs, cursor changes between clicks, partial/rejected transfers, manual slot
changes, disable/re-enable, competing owners, effect changes, multi-platform routes, medium transitions, trapped
banks and context loss. Fake clocks, click/send adapters and terrain fixtures avoid mutating real inventory in tests.

### Passive identity evidence and operational statistics

One shared collector should combine already received profiles, loaded entities, team/rank metadata, attributed chat
and recent removal. Prefer UUID identity; do not merge conflicting UUIDs by name. Exclude self, apply ignore before
watch/heuristic rules and reevaluate changed display names. Normalize formatting, width/small-capital variants and
separators before whole-word rank matching; a rank-like username or unattributed chat body is not rank evidence.

Separate confirmed/loaded/observed-online findings from uncertain unlisted, team-only or recently removed evidence.
A completely server-hidden identity cannot be discovered passively. Weak evidence needs an observation window,
expiry and bounded history; an offline team must not refresh an online claim forever. Debounce per identity,
aggregate alert overflow and keep automatic disconnect opt-in and dependent on strong evidence. Scope late callbacks
to their original session. Passive collection does not authorize command probes or hidden requests.

Name every metric's numerator, denominator and source. Count unique local completions separately from attempts and
server confirmations. Maintain session totals, rolling/average/defined-peak rates and availability states separately.
Use bounded deduplication, parse styled scoreboard labels/prefixes/suffixes and configured compact number formats,
and use decimal arithmetic for balances. Zero differs from missing/unparseable data. A new objective, source, gap,
world or session starts a new baseline. Net balance changes include spending/transfers; do not call them gross
revenue. Align action and balance windows before per-action estimates, warm up short intervals, and freeze ended
sessions consistently. Test huge/negative/zero deltas, duplicate callbacks, missing/replaced sources and old-session
updates; display uncertainty instead of inventing server-confirmed outcomes.

---

## 8. Render and world-visual techniques

These patterns should be read-only with respect to gameplay traffic. Audit optional input, command, option and
packet side effects separately; a render-only claim does not establish server policy acceptance. The rendering
approach still matters for correctness across engine versions:
- **True 3D world-space box ESP** (implemented as an ESP "World" mode, factored into a reusable `WorldMesh` +
  `WorldRenderTypes`) — build the box in **camera-relative world space** and **submit it inside the level render pass**
  (`submitCustomGeometry` on the level-submit event), so edges depth-test and occlude against terrain like real world
  geometry — no bobbing/FOV drift, no behind-camera flicker. Mechanics worth copying exactly:
  - *Ribbon lines, expanded on the CPU.* Each edge becomes a camera-facing **quad**: side direction
    `normalize(tangent × eyeRay)`, half-width in world units `= (halfPx + 1px) · worldPerPx · depth` so the *on-screen*
    width is constant at any distance, with a 1px anti-aliased **feather** carried in `UV0.x` (signed pixels from the
    line centre) and the core half-width in a per-vertex `LineWidth` attribute. `worldPerPx = 2 / (fbHeight · proj.m11)`.
  - *Near-plane clipping, not dropping.* An edge with one endpoint behind the camera is **trimmed** to a near plane
    (`depth 0.1` along the forward vector — lerp both position and colour), never discarded. This is the fix for the
    screen-projected ESP's flicker as a corner crosses behind you.
  - *Visible / hidden depth pair.* Two render types partition the screen by depth (reversed-Z: visible `GEQUAL`, hidden
    `LESS`); draw the faded through-wall "hidden" pass first (~0.28 alpha), then the "visible" pass. Both carry the same
    small depth bias so faces lying on a block don't z-fight. Filled faces are the edge colour at ~14% alpha.
  - *2D fallback, also fixed.* The simpler **screen-projected** mode projects the 8 corners and draws 2D lines, but now
    keeps only the **in-front** corners and shrinks the box to their bounds, instead of discarding the whole box the
    moment one corner goes behind the camera (the old flicker). Keep a shared **world projector** that captures the
    *exact* modelview (camera × view-bob × hurt-shake) and projection (dynamic FOV) the level drew with this frame, so
    projected overlays line up with the world. Wrap the World-mode submit in a try/catch that disables the module on
    error, so a render exception can't take down the frame.
- **Block / ore ESP ("x-ray", done right).** The classic x-ray — cancel the chunk-render of every non-target block —
  needs chunk-render hooks at class *load* time and **breaks under an optimized-renderer mod** (it replaces the vanilla
  chunk pipeline), and can't be added from an attach-time inject (those classes are already loaded). Do it as
  world-space ESP instead: scan loaded chunk *sections* a few per tick (skip any section that can't contain a target via
  its palette), collect matched blocks from the same block-picker the rest of the client uses, and draw through-wall
  boxes/tracers in the level pass (the line infra above). A **cave mode** — only blocks touching a non-opaque neighbour
  (exposed ores) — cuts the clutter. Works with optimized renderers, works injected, reuses the ESP code. (Tracer
  detail: draw the occluded segment at the line's *own* colour, not a terrain-blended faint alpha, or its colour shifts
  where it passes behind a block.)
- **Chams** — draw target entities *through walls* (depth-test disabled) in their skin or flat colours (one colour when
  visible, another behind walls). Entities drawn by chams must be **exempted from render culling** (frustum, occlusion
  raytrace) or they vanish when enough blocks hide them.
- **Framebuffer / edge-detect outline** — render targets to an offscreen buffer, then run an edge-detect pass to draw a
  clean silhouette outline, instead of a wire box. More GPU, nicer look.

---

## 9. Anticheat bypass and validation

Use the single [anticheat reference](references/anticheat-bypass.md) for detector families, click/placement validation,
rotation output, movement/packet consistency, corrections and reproducible calibration. `modules.json` adds concrete
per-module `bypass_tips`, `prerequisites`, `flag_triggers` and `validation.scenarios`; resolve aliases before adding a
new module. General ownership, state and queue mechanics remain in this skill so the reference need not duplicate them.

A candidate strategy must respect the target server's authoritative state. Similar-looking motion, random delays,
a local field/attribute change or a local warning's silence does not establish a bypass. Label source-confirmed
constraints, simulation checks, bytecode-hook verification and actual server-issued outcomes separately. Server
acceptance remains unverified unless a matching implementation/version/configuration was observed in use.

---

## 10. Movement physics and input consistency

Movement automation needs the target engine's actual physics, permissions and state. These commonly encountered
constants illustrate a model; verify its order, attributes, effects and fluid rules against the supported version.
A client-only attribute edit is not proof that a server or prediction check observes the same value.

**Vanilla per-tick integration** (player, one tick): apply input acceleration to velocity → **move** with a per-axis
collision sweep (the same Y-then-X-then-Z sweep the prediction sims use, §4) → apply drag/friction to set up next tick →
apply gravity. The constants that matter:
- **Gravity / vertical drag:** `vy = (vy − 0.08) × 0.98` (0.08 gravity, 0.98 drag) — the same step the fall sim uses.
- **Horizontal friction:** next-tick `vx,vz ×= friction`, where `friction = onGround ? blockSlipperiness × 0.91 : 0.91`.
  Default block slipperiness **0.6** → ground friction **0.546**; air **0.91**. Slipperiness: ice/packed-ice **0.98**,
  blue-ice **0.989**, slime **0.8**.
- **Acceleration applied to input:** on ground `moveSpeed × (0.21600002 / friction³)`; in air a flat `≈0.02`
  (independent of friction). `moveSpeed` = the walk-speed attribute (base **0.1**) × **1.3** while sprinting (sprint is a
  transient +30% attribute modifier, *not* a velocity hack).
- **Jump:** `vy = 0.42` (+ `0.1 × (JumpBoost+1)` with the effect); a **sprint-jump** adds a one-off horizontal
  `0.2` along the facing yaw — the single biggest legal burst of ground speed, and the honest basis for Bhop.
- **Step height:** the `STEP_HEIGHT` attribute, default **0.6**.
- **Use-item slowdown:** while `isUsingItem()` and not riding, the forward/strafe **input** is scaled by **0.2** before
  acceleration (eating, drinking, bow, shield). Sneak scales input by **0.3**. These are *input* multipliers, not speed
  caps — which is exactly where NoSlow hooks.

**The modules, and what each must respect to survive prediction:**
- **Step** — add a **transient `STEP_HEIGHT` attribute modifier** of `(height − base)` while on the ground (the vanilla
  mount/effect mechanism: `addTransientModifier(ADD_VALUE)`), removed off-ground and on disable; never touch the base.
  A transient client attribute alone does not establish server permission: check whether the server shares and
  accepts that value. Ground-gate the intended step and never replace it with an unexplained position jump.
- **Speed / Bhop** — a **staged launch** on the jump tick (take the legal `0.2` sprint-jump boost) then let per-tick
  friction decay carry the momentum, re-launching each jump. Keep peak horizontal **≤ what accel+friction can reach**:
  a sustained flat over-speed is the classic survivalfly/speed flag, whereas a decaying, re-launched arc reads as real
  momentum to a threshold AC but still requires validation against server-authoritative acceleration and collisions.
- **Strafe / air-accel** — rewrite the *air* input each tick so you accelerate toward your move vector, respecting the
  **0.02 air-accel cap** per tick; never add velocity the input itself couldn't.
- **LongJump** — a slipperiness-aware launch (exploit low-friction surfaces), but horizontal must still decay by the
  block's friction each tick and the launch impulse must be one a jump could legally produce.
- **NoSlow** — a **`modifyInput` redirect** that skips *only* the `0.2` use-item input scale (`NoSlow.active()` read by a
  movement-input mixin), leaving sneak and every other modifier. **Honest caveat:** a prediction AC *models* that `0.2`
  slowdown, so walking full speed while using an item diverges from its prediction — NoSlow conflicts with checks that model use-item slowdown. Do not label skipping the multiplier a validated
  bypass merely because the rest of the movement code stays unchanged. This is the cleanest illustration of
  the §9 split: surgical and "legit-looking," yet fatal on the prediction AC precisely because it's physically
  inconsistent.
- **KeepSprint / OmniSprint** — distinguish a valid retained latch from forcing a new start after vanilla cancelled
  it. Entry and continuation predicates differ by movement mode/version; forward+strafe can retain authorized sprint
  flight. Avoid repeated direct reassertion and competing sprint owners. Backward/no-forward boosts require separate
  justification; setting a vanilla field alone does not establish valid movement or server acceptance. Use a bounded ordinary key press, observe the actual latch and release only the synthetic key; see below.
- **Velocity (anti-KB)** — scale `deltaMovement` after the server applies knockback, with **precision jitter** so the
  result is never a clean fraction of the push (§7). Independent H/V percentages read as partial, legit-looking reduction
  rather than immunity.

**Consistency boundary:** input-driven movement is easier to compare with an unmodified baseline than arbitrary
position writes, but the server must actually authorize the relevant abilities/attributes. Packet-only observations,
world state, permissions and detector configuration all matter. Numerical thresholds and added randomness do not
turn unsupported movement into a demonstrated bypass.

### Input-state transitions and optional authorized flight

The same controller discipline applies to ground routes, swimming, gliding and server-authorized powered flight:
separate entry preference, retained intent, actual game state and physical key state. Predict the final normalized
input after every producer/veto, including diagonals, effects, current momentum and realizable braking. Preserve the
target version's integration/collision order and server-provided speeds; independent clear horizontal/vertical rays
do not establish clearance for a simultaneous full-body move under an overhang.

For authorized flight only, a tapped sprint can retain its latch while valid forward/strafe and altitude input
continue. A heading threshold used for entry need not be a continuation predicate. Count stable entry once per input
tick, adopt a valid manual latch, release the synthetic key after observing vanilla sprint, and back off after a
rejected start. Never force the field true repeatedly after the game cancels it. Release for real braking, unsafe
clearance, no forward input, lost permission, menus or recovery; arbitrate generic sprint and task-specific producers.

Synthetic jump pulses can accidentally exercise the manual double-tap flight toggle. Suppress only the task-owned
timer accumulation while already-authorized flight is active, preserving manual double jump outside that scope.
Verify that narrow hook in load-time and attach builds. Do not compensate for a missing hook by granting permission,
writing velocity or inventing extra movement packets. Flight acceleration differs from the ground sprint modifier;
inspect the supported version rather than transplant its multiplier. Longer valid passes and tangent-continuous
handoffs reduce gratuitous state churn, but never justify unsafe speed retention.

Probe retained-state stability over turning/altitude changes, unsafe immediate release, rejected starts/cooldowns,
repeated-query idempotence, modified speeds/effects, fixtures, concave corners and return from outside the route.
Controller tuning values are examples to measure, not anticheat thresholds.

---

## 11. The packet-interception engine

Backtrack, FakeLag, Blink, KnockbackDelay and Velocity-delay all sit on one small service that **holds packets on the
client's own connection and lets them go later, in order**. Getting its architecture right is what keeps "delay" from
becoming "desync-until-flagged" or "timed-out."

The contracts below require connection/world generations, explicit control decisions and version-specific tick
boundaries. A concurrent queue and a zero-delay exemption are insufficient. Detector-facing experiments belong in
the [anticheat reference](references/anticheat-bypass.md#packet-order-and-corrections).

**Queues.** Three lock-free queues (concurrent, because incoming is decided on the Netty thread and released on the main
thread): `incoming` (everything KnockbackDelay holds, plus whatever arrived behind it — one global line), `entityHeld`
(one target's movement packets, for BackTrack — a line of its own that can jump ahead of nothing it arrived after), and
`outgoing`. Each held record carries packet, monotonic arrival sequence, originating connection/session/world
generation, release deadline and observation time (incoming also its listener; outgoing callback/flush flags).
Use sequence cutoffs for release commands; wall-clock milliseconds cannot distinguish causal order within one tick.

**Per-module rules.** A rule is a one-method callback: `holdUntil(packet, now)` returns **`0` = let it through**, else
the timestamp it may go. An **outgoing** rule answers "how long does *this* packet wait"; an **incoming** rule the same
for received packets. There are two shared **slots** — one outgoing, one incoming(knockback) — plus the per-entity
BackTrack slot. Each slot is **owner-aware**: `setOutgoingRule(ownerModule, rule)` records the owner, and
`clearOutgoingRule(owner)` is a **no-op unless that owner still holds it**, so a module disabling can't rip out another's
rule. A would-be second claimant calls a `PacketConflicts` helper first: if another *enabled* module holds the slot, that
one is switched off with a toast ("FakeLag turned off Blink — both use outgoing packet timing") instead of silently
winning and leaving the loser enabled-but-dead.

**Re-entrancy-safe flush/dispatch.** Releasing a held packet must not recurse back into the rule. Outgoing uses a
**one-use receiver+packet token** carried in thread-local state: exempt only that replay invocation and restore the
previous token in `finally`. A broad boolean also exempts unrelated nested sends. Incoming is replayed on the main
thread through **vanilla's own dispatch** (an accessor onto the connection's packet handler), guarded so a packet whose
connection has moved on — listener swapped, configuration phase entered, disconnected, or `!isAcceptingMessages` — is
dropped, not force-fed into the wrong state. Listener identity alone is insufficient: respawn/dimension replacement
can keep the same listener. Queue clearing must also invalidate an in-flight old-session producer.

**The allowlist (what you may delay).** Limit ordinary movement delays to movement and its required protocol batch
markers. A modern tick-end marker passed through a flush-on-live path can empty the movement queue every tick.
Distinguish ordered pass, flush-before-pass and safe immediate control handling; returning `0` alone does not bypass
an already-held incoming head. **Block/use actions** carry a client sequence the server acks and predicts against — holding them
desyncs blocks and inventory. **Container clicks, keep-alives, chat, teleport-confirms** go live or you time out / brick
the connection. And **protocol-critical** inbound packets (disconnect, start-configuration) must never wait: the engine
forces everything ahead of them to release *now* and queues them immediately behind, so order is preserved without
stalling the handshake. When a live packet follows still-held ones, **flush the held ones first** (on the main thread,
synchronously) so the server never sees the later packet before the earlier.

Keepalives need effective handling even behind an indefinite hold, and world/respawn barriers need explicit
drain/discard semantics. Bound queue count and age globally, independent of optional module Auto Send settings.

**Ordering across the two incoming lines.** When a globally-held (`ALL`) packet is released, any `entityHeld` packets
that were *queued before it* are released first — the global line and the per-entity line merge back into real arrival
order, so BackTrack's frozen target doesn't teleport relative to the rest of the world on release.

**Flush-and-pause triggers.** The queue instantly drains and stands down on: **your own attack packet** (so a held
position can never cost you the hit you're about to land — the "flush instantly when your attack would hurt them" rule),
**taking knockback** (your real position jumped), and **any server position-correction / teleport** (tracked as
`lastPositionCorrection` on the network thread the moment a `ClientboundPlayerPosition` arrives). Modules also cap a
held packet's **age** (a Max-Desync setting — release once the server is > N ms behind where you really are) to bound retained state; validate against the target protocol and detector configuration (§9).

**Hazards the design avoids:** holding a keep-alive → kick; holding a block/use → inventory/block desync and rejected
actions; holding past a setback → acting on a stale position (the correction-validation discussion in §9); speeding the clock instead of
delaying → a timer flag; touching the *integrated server's* connection → guard every entry on "is this the client's own
play-state game connection." Delay only, release in order, flush on anything that would fight the server.

### Lifecycle races, replay and observability

A producer may pass a connection check, pause across disconnect cleanup and enqueue after the queue was cleared.
Invalidate generations and serialize or atomically revalidate enqueue/dispatch against lifecycle changes. Reset
sequence cutoffs, correction and sent-state metadata with the session. Publish owner and rule consistently; an
owner-checked release alone does not synchronize in-flight producers.

Represent `HOLD`, `ORDERED_PASS`, `FLUSH_BEFORE_PASS` and semantically safe `IMMEDIATE_CONTROL` explicitly. Preserve
protocol batches, listener/world barriers, write callbacks and flush semantics; a discarded write needs completion
or cancellation rather than an unresolved promise. Bound global age, count and retained bytes independently of
optional auto-release toggles. Multiple incoming lines need a sequence-based merge, not timestamp guesses.

Count attempted, queued, dispatched and dropped packets separately; replay visiting the send hook again is not a
second actual dispatch. Scope observation to connection/session and refresh baselines on ownership changes. Test
keepalive behind an indefinite hold, same-listener world replacement, a producer paused over disconnect, tick-end
markers, same-time release cutoffs, nested sends, callback completion, overflow and correction followed by movement.
A probe reproducing today's defect is audit evidence; acceptance tests should assert the repaired invariant.

---

## 12. Config & persistence

Settings are the single source of truth (§1), so persistence is just *serialising the settings tree* — and the
interesting engineering is **migration** (a shipped client renames and merges things constantly) and a **shareable
config marketplace**.

**Per-setting (de)serialisation.** Each `Setting<T>` has `toJson()` / `fromJson(element)` for its own type (a bool is a
primitive, a `Range` a `{min,max}` pair, a `Color` an ARGB int + chroma flags, a `Mode` the enum name, an `ItemList` an
array, …). Its storage **key** is derived from its name (`name.toLowerCase().replace(' ', '_')`), so renaming a setting
*changes its key* — which is why every setting also carries **`legacyKeys("old_id", …)`**: when its own key is absent
from a saved object, `loadLegacy` tries each old key in order and loads from the first present. That one hook makes a
rename config-compatible with zero other code.

**Per-module.** `Module.toJson()` writes `{enabled, keybind, bindMode, favorite?, hidden?, settings:{key→setting}}`.
`fromJson(obj, applyModuleStates)` restores them, and for each setting whose key is *missing* calls `loadLegacy` so a
restructured setting still loads. The **`applyModuleStates`** flag is the subtlety: `false` applies only settings
(and keybind/favorite/hidden), leaving each module on/off as it is now; `true` also restores the saved enabled state
(but never for a HOLD-bind module). Disk and live loads pass `true`; a marketplace/profile load passes the user's
"Auto-load module states" preference (default off, so applying someone's config doesn't suddenly enable their modules).

**The file & load order.** One `config.json`: `{version, styleVersion, guiVersion, modules:{id→module}, gui}`, where
`id = name.toLowerCase().replace(' ', '_')`. Load runs **strictly in order**: (1) rename/merge passes mutate the *raw*
`modules` JSON *before* any module reads it; (2) each live module reads its object; (3) cross-module migrations that need
the live objects (e.g. Chams→ESP); (4) GUI state; (5) versioned default-migrations. Saves are **debounced** (a dirty
flag flushed ~1.5 s later on the client tick) so rapid edits batch, with an "Auto Save off" mode that holds changes for
the explicit save points (menu close, client stop).

**Versioned migration — three shapes, all idempotent and non-destructive:**
- **Renamed module** — carry the old id's whole object to the new id if the new one is absent (`block_search → block_esp`,
  `perspective → freelook`).
- **Renamed/moved *setting*** — the per-setting `legacyKeys` hook above, plus, where keys would collide on a merge, an
  explicit rename during the raw-JSON pass (e.g. two merged modules' `delay` ranges become `totem_delay` / `heal_delay`).
- **Merged / split modules** — the heaviest: a monolithic "Visual Tweaks" **splits** into one module per feature group
  (each new module inherits the shared settings object and is enabled from `moduleOn && thatGroupSwitchOn`); three
  separate modules **merge** into one "Auto Item" whose sections turn on from the old modules' enabled states; a module
  **dissolves** into two homes (an equip half into one module's section, a smash half into another's triggerbot), each
  key copied into its new home only if absent. The guiding rules: **first-writer-wins per key**, only ever *fill* a
  target the config doesn't already have, and run dependent migrations in order (merge before the dissolve that targets
  it).
- **Versioned *defaults*** — a monotonic `styleVersion` / `guiVersion`: when the client's default look changes, bump the
  constant and, for configs below it, **move only values still sitting at the old default** (a scale/colour/corner the
  user explicitly picked is detected by comparing to the old default and left alone). This ships a nicer default without
  overwriting anyone's choices.

**Config profiles & a shareable marketplace.** `export()` serialises every module's settings (plus keybind/favorite/
hidden) but **not** the click-GUI panel layout, so a shared config doesn't move someone's windows; `importConfig(root,
applyModuleStates)` runs the *same* rename/merge passes (a shared config can predate a rename too) then applies, honoring
the module-states toggle. On top sits a backend: **private** configs saved to your account, **published** copies that go
through review (`private → pending → approved`), browse/detail/apply with downloads, likes, bookmarks and thumb reviews.
The session token arrives through an explicit bootstrap/entry-point handoff rather than a JVM-wide property; apply fetches JSON and hands it to
`importConfig` on the main thread, and submit/export reuse the exact same serialisation — one format for disk, live sync,
and the marketplace.

---

## 13. A note on scope

This skill covers the *behaviour* layer. The runtime/loader layer (how code is loaded and hot-reloaded, plus the
dev/testing harness) is the `silentkit-runtime` skill; the menu/overlay/theming/render-abstraction layer is
`silentkit-interface`. Keep gameplay logic, loading, and UI in separate skills so each stays a clean, portable
reference.
