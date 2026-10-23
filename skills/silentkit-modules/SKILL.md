---
name: silentkit-modules
description: >-
  Engineering reference for the module/method layer of a ghost client: the module/event/setting architecture,
  a shared humanization engine (eased rotation, mouse-GCD quantization, timing realism), silent-aim with rotation-
  ownership arbitration, vanilla-physics prediction (fall / flight / projectile sims), aim-control math (PD+I,
  leading), and the combat/world technique patterns. Use when designing or extending modules, or starting a client
  from scratch. Brand-neutral and framework-agnostic; pair with the queryable database at references/modules.json.
---

# SilentKit · Modules & Methods

A build reference for the behaviour layer of a ghost client. It is deliberately brand-neutral: it describes
*patterns and math*, not any one project's code. API names are illustrative (modern Minecraft-style), but the ideas
port to any game/engine with a tick loop, an input pipeline, and an outgoing-packet path.

The companion file `references/modules.json` is a structured catalogue of every module and technique below — query it
instead of re-reading prose when you need "which modules exist / what does X do / what signals does Y use."

The single most important idea: **a server-side anticheat only ever sees your packets** — rotations, positions,
interactions, attacks, their timing and their order. Every technique below is ultimately about making that packet
stream indistinguishable from a human's, or about acting on information (prediction) a human couldn't compute but
whose *output packets* are still legal. Client-side-only modules (render, HUD, performance) send nothing new and are
therefore unflaggable; they're catalogued for completeness but carry no detection surface.

**§9 (Anticheat threat model)** maps the real detectors — Grim, NoCheatPlus, Vulcan, Verus, Intave, Matrix — to the
counter each technique relies on; read it first when deciding whether a given module is safe on a given server. The
behaviour engines it points back into are §2 (humanization), §3 (silent aim), §6 (timing), §10 (movement physics) and
§11 (the packet-interception engine).

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

---

## 2. The humanization engine

The shared realism layer. Build every automated behaviour on it, never ad-hoc linear math — one tuned statistical
fingerprint across all modules is itself less detectable than several different ad-hoc ones.

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
  Plus a hair of positional jitter while turning (`jitter(0.12)` on yaw, `0.08` on pitch) above 1.5° of remaining delta.
- **Overshoot** — a turn over ~25° flicks `min(|delta|·0.12, 6)°` past the target, then the offset decays (`×0.55`/tick)
  and the normal pull settles back. Rate-limited (~500 ms) so it isn't on every micro-correction.
- **Flick guard** — a hard `±70°/tick` ceiling: no matter how high aim speed is set, never turn more in one tick than a
  hand plausibly could.
- **GCD snap** (server path only).

Two entry points: `camera(...)` eases from the *live* camera (so your own mouse still counts and the view interpolates
smoothly — **no grid snap here**, snapping a per-frame camera step reads as a visible stair-step) and `silent(...)`
seeds from itself/the camera and **does** grid-snap, for the server rotation.

**The mouse-GCD rule (the key anti-detection realism).** A real mouse turns only in whole "counts," so every rotation
the vanilla client sends is a multiple of a sensitivity-derived step. The engine mirrors the exact vanilla math:
`f = sens·0.6 + 0.2`, then `gcd = f³ · 1.2` **degrees per count**. A detector that reconstructs this GCD (e.g. Grim's
AimProcessor) flags any rotation delta not on the grid. Rules:
1. Snap the rotation that goes *on the wire* to the grid, anchored on the last sent value:
   `snapped = base + round((target−base)/gcd)·gcd`.
2. If a snapped step rounds to 0 but the target is still ≥1 count away, take the smallest grid step that *progresses*
   (`sign(delta)·gcd`) — never stall short of a reachable target.
3. **Carry the sub-count remainder** across ticks instead of snapping-and-dropping it — a real mouse accumulates.
4. Advance eased aim on a real `dt` time base (sub-tick) so the yaw-rate signal isn't a 20 Hz staircase; snap only the
   value that actually leaves on a packet.

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
  - **MLG/auto-bucket** reuses the sim to find the landing, then validates a **top-face raytrace** before placing water.
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

1. **Target-rate feed-forward.** A pure exponential ease *always trails* a strafing target by a roughly constant angle.
   So track the target's own angular velocity — `ffRate = ffRate·0.6 + (Δwant/dt)·0.4` (a low-pass) — and add
   `clamp(ffRate·dt, ±6°)` to the step, moving *with* the target instead of lagging it. (A full controller adds a
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

**Auto-clicker — make the *statistics* human, not just the mean CPS.** Run it per-frame so rates above 20 CPS aren't
tick-bound. Click *styles* and fatigue are the start; the levers that actually defeat a click-distribution check:
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
- **Misclicks:** occasionally skip a click, or add a quick double (18–40 ms apart).
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

**Packet timing — one owner-aware queue** (full architecture — queues, re-entrancy, ordering, allowlist — in §11). A single `PacketDelay` service holds packets on the client's own connection
and replays them in order on the main thread. It exposes **owner-aware rule slots** (outgoing, incoming/knockback,
per-entity) claimed with a module token; a second claimant notices the clash and the conflicting module is auto-disabled
first. Refinements shared across FakeLag / Blink / KnockbackDelay / BackTrack:
- Cap a held packet's **age** (a Max-Desync setting, e.g. release once the server is >N ms behind where you really are)
  so movement never desyncs far enough to flag.
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
    the next place fires immediately. Interactions carry explicit coordinates, so the aim is **purely for legitimacy**
    (eased through `HumanAim`, silent or real).
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
    in reach. Without it every placement lands dead-centre on the face, a trivial tell. The planner's `hitFor` /
    `rotationTo` use the *un-jittered* centre so aim cost is stable.
  - **A shared A\* placement planner** (`PlacementSearch`) — now implemented, not just the aspiration. `frontier(targets)`
    returns the subset fillable *this tick* (replaceable *and* a reachable sturdy face exists), ordered **cheapest aim-
    movement first** (`rotCost = |Δyaw| + |Δpitch|` from your current look to the click face), so a caller places one or
    a few per tick with the smallest turn and the frontier re-expands next tick as fresh blocks create new supports.
    `planTo(goal, maxSteps)` is a **bounded best-first (A\*)** over the 6-neighbourhood to bridge to a goal you can't
    reach yet: seed the open set with every placeable-now cell near the goal, treat each expanded cell as solid-once-
    placed, order by `path.length + blockDistance(goal)` (cost = steps, admissible heuristic), prune past reach/budget,
    and return the placement order ending at the goal. Surround already runs on `frontier()`; scaffold, clutch and
    auto-ladder can share the same solver with different goal tests — "which block next" becomes one planner.
  - **Scaffold** modes: *Legit* (predictive auto-sneak at edges — crouch when a fixed look-ahead along your heading puts
    your feet over air, released on a randomized human hold; you place), *GodBridge* / *TellyBridge* (places under your
    feet as you walk / only while airborne, diagonals included, never above start-Y + a Y-increase). Key correctness
    bits: **half-block-aware placement Y** (feet at `.5` on a slab → build from `floor(y)`, else `floor(y)−1`), a
    nearest-first ring of feet spots (next-tick landing, diagonal corner-fills, current column), and an **Expand
    re-anchor** — if the feet column can't be filled (you clipped a corner / stepped a gap), reach out to the 8
    neighbouring columns so you catch yourself instead of falling.
  - **Clutch** scans from just under the feet downward through reach, trying the whole 3×3 ring plus the momentum/landing
    column nearest-first, places at the highest reachable support, then *returns slot and view*. The look-down is eased
    and **cosmetic** (the block is placed off the hit result, not the rotation), and the key guard is a `released()`
    check (landed / no longer in a dangerous fall / timed out) so the view or silent rotation **never sticks** mid-air.
- **Enchant-weighted item scoring.** A shared comparator so auto-armour, auto-weapon, "best-gear-only" chest-steal and
  the inventory manager all agree: score armour as armour points + toughness (half-weighted) + protection; a weapon by
  attack damage + small per-enchant bonuses; a tool by dig speed + efficiency/fortune. Driving it off the item's own
  **attribute modifiers** keeps it robust across game versions (higher is always better). Feeds a best-per-slot equip +
  a 2-set quick-swap, and a "better than what's equipped" gate for looting.
- **Anti-bot behavioural score.** Replace binary flags (invisible / never-moved / not-in-tab) with an accumulating
  per-entity score summed from *independent* signals since you first saw them: sustained air-hover (physically
  impossible — count consecutive ticks airborne with ~0 vertical motion, not in water, not riding; >1 s ≈ conclusive,
  +10), not in the tab list (+4), NPC/red-coloured name tag (+5). Threshold it (e.g. 8). Won't trip on a player standing
  still, and no single weak signal false-positives. **Compute the verdict once per tick and cache it** on the per-entity
  track, so the many per-frame callers read a cached boolean instead of re-scoring. Expose `ignoreForCombat` /
  `ignoreForVisuals` so aura, auto-clicker, tracers, radar and target-HUD all skip flagged entities. **Teammate
  detection** rides the same gate (so you never attack your own team): a player is a teammate if they share your vanilla
  scoreboard team, *or* share a non-white name `TextColor` (both non-null, equal, value ≠ `0xFFFFFF`), *or* share a
  non-empty scoreboard-team **prefix string** — the three ways servers actually mark teams.
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
- **Hitbox expansion done legally.** When you widen a target's hitbox for easier hits, **project the outgoing
  interaction vector back onto the real box edge** so the attack packet the server receives still lands on the genuine
  hitbox — the expansion helps *you* aim, but the server sees a legal hit, not an impossible-angle one.
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
- **Velocity precision jitter.** When reducing knockback, scale the server's push by *raw floats* and add ±~3% per-hit
  jitter (`h,v ±= (rand−0.5)·0.06`, clamped `[0,1]`) so the result never lands on a clean fraction (an exact `0.40`, a
  perfect `0`) — a non-physical signature. The jittered result reads like ordinary lag variance.

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

---

## 8. Render / world-visual techniques (detection-free, but worth doing right)

These send no packets, so they never flag — but the *rendering* approach matters for correctness across engine versions:
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
- **Chams** — draw target entities *through walls* (depth-test disabled) in their skin or flat colours (one colour when
  visible, another behind walls). Entities drawn by chams must be **exempted from render culling** (frustum, occlusion
  raytrace) or they vanish when enough blocks hide them.
- **Framebuffer / edge-detect outline** — render targets to an offscreen buffer, then run an edge-detect pass to draw a
  clean silhouette outline, instead of a wire box. More GPU, nicer look.

---

## 9. Anticheat threat model

Before any module is "safe," know what is watching. A server anticheat only ever sees your packet stream, and it runs
a fixed set of **detectors** over it. A technique is safe on a server exactly when none of that server's detectors can
separate its packets from a human's — so "is X legit" is never a yes/no, it's "which detector would X trip, and does
this server run it." This section maps the major anticheats, the detector families, *why a clean/non-physical value is
what gets caught*, and which engine elsewhere in this skill keeps you under each.

**The anticheats, by philosophy** (design against the strictest one you'll meet):
- **Grim (GrimAC)** — *prediction-first*, and the one to assume. It reimplements vanilla physics, replays **your own
  inputs** through it each tick, and bounds your real position to a tiny **offset** (fractions of a block) from the
  predicted one — any motion your inputs can't justify grows the offset and flags. It also reconstructs your
  mouse-sensitivity **GCD** (its AimProcessor) and checks server-set **velocity/knockback** and **explosion** motion
  precisely. It models sprint, use-item slowdown, **step height via the attribute**, and rotation granularity, and uses
  **transaction** (ping) packets to pin how stale your position may legitimately be.
- **NoCheatPlus (NCP)** — *threshold/heuristic*, legacy but everywhere. Independent checks with violation levels:
  survivalfly (speed/air), fastbreak, fastplace, direction, reach, morepackets/timer, autoclicker. It doesn't fully
  simulate physics, so it's beaten by *being under the number* (raw speed, reach distance, packets-per-second) rather
  than by being physically consistent. Uses **keepalive** for latency.
- **Vulcan** — heuristic + light prediction; strong motion/aim-pattern and "impossible value" checks (speed, phase,
  aim-GCD consistency, autoclicker regularity).
- **Verus** — aggressive *statistics* on aim and clicks: post-hit rotation, autoclicker variance, packet-order
  ("badpackets").
- **Intave** — strong rotation + movement consistency; sensitive to non-human aim curves and to client-only rotations
  that don't move the body.
- **Matrix** — heuristic combat/movement: reach, hitbox, killaura-pattern.

**Detector families, and why a clean value flags:**
1. **Movement prediction / physics replication** (Grim's offset engine; NCP survivalfly as thresholds). The AC derives
   the set of positions your inputs *could* produce this tick; a position outside it flags. A too-exact over-speed, a
   step with no attribute to justify it, full walking speed while using an item, a held position-packet that has
   drifted too far behind where you really are — each is motion the replay can't reach.
2. **Rotation checks.** (a) **GCD** (Grim AimProcessor, Vulcan, Verus): a real mouse turns in whole sensitivity-derived
   counts, so every legit rotation delta is a multiple of that GCD (§2). A delta *off* the grid can only come from code.
   (b) **Smoothness/pattern**: a *uniform* yaw-rate, a symmetric speed band, or a perfectly frozen lock on a moving
   target is too even — real aim is right-skewed with microjitter and drift. (c) **Snap / aim-duration / cinematic**: an
   instantaneous large turn (or an inhumanly *smooth* over-long one) reads as non-human.
3. **Timing / CPS distribution + packet-order.** Symmetric or metronomic click gaps, zero press→release variance, a
   constant CPS, or clicks that free-run with no input — all are statistical tells even when the *mean* CPS is human.
   Packet-order checks catch an action sequence a vanilla client never emits.
4. **Reach / hitbox.** An attack whose eye-ray-to-hitbox distance exceeds ~3 blocks, or that lands at a geometrically
   impossible angle, is flagged regardless of how the rotation was produced.
5. **Post / combat-order.** The rotation or motion *right after* a hit (Verus), hits landing before the attack cooldown
   has recharged, or an attack packet out of order with its swing/rotation.
6. **Setback & rubberband behaviour.** How you react to a server position-correction: a client that keeps acting on its
   old (pre-setback) position, or doesn't accept the teleport, desyncs further and flags.
7. **Transaction / ping (keepalive) latency.** The AC times a round-trip (Grim transactions, NCP keepalive) so it knows
   your true latency; this both bounds "legitimate" staleness for (1) and makes *holding* one of those packets a direct
   tell (and often a disconnect).

**Why non-physical "clean" values are the giveaway** (the recurring theme): a perfect knockback fraction (post-KB motion
exactly `0.40×` the push, or a perfect `0`), an exact block-face-centre click (`0.5, 0.5`), a uniform turn speed, or a
full-strength hit landing mid-cooldown are all values the game's own randomness and your network jitter would never
produce. The counters below all work the same way — put *human-plausible noise* back where the cheat removed it, or
derive a value the AC itself would accept.

**Detector → counter map:**

| Detector family | What trips it | Counter in this skill |
|---|---|---|
| Movement prediction (Grim offset) | motion the replay can't reach; held position drifting past predicted | change the same inputs/attributes the AC models, not the output position (§10); packet-delay allowlist + Max-Desync age cap + flush-on-attack/correction (§11) |
| Rotation GCD (Grim/Vulcan/Verus/Intave) | deltas off the sensitivity grid | snap the *wire* rotation to the grid, anchored on last-sent, carrying the sub-count remainder (§2, §3) |
| Rotation smoothness/snap | uniform yaw-rate, frozen lock, instant snap, over-smooth | log-normal per-tick pace + AR(1) drift + rate-limited overshoot + ±70°/tick flick guard (§2) |
| CPS / click distribution (NCP/Verus/Vulcan) | symmetric or metronomic gaps, zero hold-time variance, free-running clicks | log-normal gaps + OU CPS walk + repeat-gap + modelled press→release + micro-pauses + Click-Assist amplify-real-only (§6) |
| Attack cooldown / post-combat (Verus) | full-strength or 0-KB hits during cooldown | charge gate: hold each click until `getAttackStrengthScale ≥ ~0.9` (§6) |
| Reach / hitbox (all) | eye-ray-to-hitbox > ~3 blocks; impossible angle | backtrack's aim-ray dot gate + reach check (§7); hitbox expansion projected back to the real box edge (§7) |
| Explicit velocity / KB / explosion (Grim/NCP) | post-KB motion a clean fraction of the server push | velocity precision jitter ±~3%, never a clean fraction (§7) |
| Block-place direction/reach/fast (Grim/NCP) | no reachable sturdy face; exact face-centre hit-vec; place faster than vanilla | shared placer's sturdy-full-face + reach raytrace; in-plane hit-vec jitter; FastPlace left at plausible contexts (§7) |
| Timer / morepackets (Grim timer, NCP) | more movement packets per second than real time allows | never speed the packet clock; only *delay* then release in order, Max-Desync capped (§11) |
| Transaction / keepalive latency (Grim/NCP) | holding a ping / keepalive / teleport-confirm | allowlist those live; never queue them (§11) |
| Look-vs-velocity (Grim; elytra/sprint) | moving a direction you aren't facing (silent aim, backward sprint, elytra) | movement correction re-picks WASD against the server yaw, sprints only when forward (§3); elytra sets rotation at tick-end so look == move (§4) |

The practical upshot: **prediction ACs (Grim) are beaten by being physically consistent** — change what they model, not
the result — while **heuristic ACs (NCP) are beaten by staying under the threshold**. A module that's safe on one can be
instantly fatal on the other (NoSlow, §10, is the textbook case), which is why the per-module `anticheat_notes` and this
map matter more than any single "legit mode" switch.

---

## 10. Movement physics & bypass

Every movement module is a lie told *in the language of vanilla physics* — so the physics is the foundation. Reproduce
it exactly (and per engine version; the constants drift), because a prediction AC runs the same integration and compares.

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
  Survives Grim precisely *because Grim reads the attribute* and simulates the taller step, so your resulting position is
  still predicted — a teleport-up (`setPos` to the higher block) would diverge from the replay and flag. **Ground-gate
  it** so it can't climb mid-air, which no step could produce.
- **Speed / Bhop** — a **staged launch** on the jump tick (take the legal `0.2` sprint-jump boost) then let per-tick
  friction decay carry the momentum, re-launching each jump. Keep peak horizontal **≤ what accel+friction can reach**:
  a sustained flat over-speed is the classic survivalfly/speed flag, whereas a decaying, re-launched arc reads as real
  momentum to a threshold AC and is predicted by Grim.
- **Strafe / air-accel** — rewrite the *air* input each tick so you accelerate toward your move vector, respecting the
  **0.02 air-accel cap** per tick; never add velocity the input itself couldn't.
- **LongJump** — a slipperiness-aware launch (exploit low-friction surfaces), but horizontal must still decay by the
  block's friction each tick and the launch impulse must be one a jump could legally produce.
- **NoSlow** — a **`modifyInput` redirect** that skips *only* the `0.2` use-item input scale (`NoSlow.active()` read by a
  movement-input mixin), leaving sneak and every other modifier. **Honest caveat:** a prediction AC *models* that `0.2`
  slowdown, so walking full speed while using an item diverges from its prediction — NoSlow is **high-risk on Grim** and
  survives only where the AC doesn't model use-item slowdown (older NCP configs). This is the cleanest illustration of
  the §9 split: surgical and "legit-looking," yet fatal on the prediction AC precisely because it's physically
  inconsistent.
- **KeepSprint / OmniSprint** — the tick an attack or knockback clears `isSprinting`, re-assert it (`setSprinting(true)`)
  when vanilla would still allow a sprint (forward held, food > 6, not using an item, not mid-crit), so you don't lose a
  step. **KeepSprint is the genuine vanilla sprint state** and safe. **OmniSprint** (sprinting while steering sideways or
  backward) is *non-vanilla* and trips sprint-direction checks — gate it off on prediction ACs.
- **Velocity (anti-KB)** — scale `deltaMovement` after the server applies knockback, with **precision jitter** so the
  result is never a clean fraction of the push (§7). Independent H/V percentages read as partial, legit-looking reduction
  rather than immunity.

**The universal rule:** a prediction AC accepts any motion *some legal input could have produced* and flags motion no
input could — so a movement cheat survives it only by changing the **inputs/attributes the AC also reads** (sprint flag,
step attribute, jump, input vector), never by writing an output position those inputs don't justify. Heuristic ACs
instead flag raw magnitudes, so there you tune the numbers under the threshold. Design for whichever you'll face.

---

## 11. The packet-interception engine

Backtrack, FakeLag, Blink, KnockbackDelay and Velocity-delay all sit on one small service that **holds packets on the
client's own connection and lets them go later, in order**. Getting its architecture right is what keeps "delay" from
becoming "desync-until-flagged" or "timed-out."

**Queues.** Three lock-free queues (concurrent, because incoming is decided on the Netty thread and released on the main
thread): `incoming` (everything KnockbackDelay holds, plus whatever arrived behind it — one global line), `entityHeld`
(one target's movement packets, for BackTrack — a line of its own that can jump ahead of nothing it arrived after), and
`outgoing`. Each held record carries `{packet, releaseAt, queuedAt}` (incoming also the `PacketListener` it must be
replayed into; outgoing the `callback`/`flush` flags) so order and timing survive the wait.

**Per-module rules.** A rule is a one-method callback: `holdUntil(packet, now)` returns **`0` = let it through**, else
the timestamp it may go. An **outgoing** rule answers "how long does *this* packet wait"; an **incoming** rule the same
for received packets. There are two shared **slots** — one outgoing, one incoming(knockback) — plus the per-entity
BackTrack slot. Each slot is **owner-aware**: `setOutgoingRule(ownerModule, rule)` records the owner, and
`clearOutgoingRule(owner)` is a **no-op unless that owner still holds it**, so a module disabling can't rip out another's
rule. A would-be second claimant calls a `PacketConflicts` helper first: if another *enabled* module holds the slot, that
one is switched off with a toast ("FakeLag turned off Blink — both use outgoing packet timing") instead of silently
winning and leaving the loser enabled-but-dead.

**Re-entrancy-safe flush/dispatch.** Releasing a held packet must not recurse back into the rule. Outgoing uses a
**`ThreadLocal<Boolean> RESENDING`**: the send-queued-packets path sets it true, so the outgoing hook short-circuits
(returns "not held") for anything it itself re-sends, and clears it in a `finally`. Incoming is replayed on the main
thread through **vanilla's own dispatch** (an accessor onto the connection's packet handler), guarded so a packet whose
connection has moved on — listener swapped, configuration phase entered, disconnected, or `!isAcceptingMessages` — is
dropped, not force-fed into the wrong state.

**The allowlist (what you may delay).** Only **movement/position** packets are ever held; the rule returns `0` for
everything else. **Block/use actions** carry a client sequence the server acks and predicts against — holding them
desyncs blocks and inventory. **Container clicks, keep-alives, chat, teleport-confirms** go live or you time out / brick
the connection. And **protocol-critical** inbound packets (disconnect, start-configuration) must never wait: the engine
forces everything ahead of them to release *now* and queues them immediately behind, so order is preserved without
stalling the handshake. When a live packet follows still-held ones, **flush the held ones first** (on the main thread,
synchronously) so the server never sees the later packet before the earlier.

**Ordering across the two incoming lines.** When a globally-held (`ALL`) packet is released, any `entityHeld` packets
that were *queued before it* are released first — the global line and the per-entity line merge back into real arrival
order, so BackTrack's frozen target doesn't teleport relative to the rest of the world on release.

**Flush-and-pause triggers.** The queue instantly drains and stands down on: **your own attack packet** (so a held
position can never cost you the hit you're about to land — the "flush instantly when your attack would hurt them" rule),
**taking knockback** (your real position jumped), and **any server position-correction / teleport** (tracked as
`lastPositionCorrection` on the network thread the moment a `ClientboundPlayerPosition` arrives). Modules also cap a
held packet's **age** (a Max-Desync setting — release once the server is > N ms behind where you really are) so movement
never desyncs far enough for the prediction/timer detectors (§9) to bite.

**Hazards the design avoids:** holding a keep-alive → kick; holding a block/use → inventory/block desync and rejected
actions; holding past a setback → acting on a stale position (the setback detector, §9#6); speeding the clock instead of
delaying → a timer flag; touching the *integrated server's* connection → guard every entry on "is this the client's own
play-state game connection." Delay only, release in order, flush on anything that would fight the server.

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
The session token arrives out-of-band (an injector-set system property), apply fetches JSON and hands it to
`importConfig` on the main thread, and submit/export reuse the exact same serialisation — one format for disk, live sync,
and the marketplace.

---

## 13. A note on scope

This skill covers the *behaviour* layer. The runtime/loader layer (how code is loaded and hot-reloaded, plus the
dev/testing harness) is the `silentkit-runtime` skill; the menu/overlay/theming/render-abstraction layer is
`silentkit-interface`. Keep gameplay logic, loading, and UI in separate skills so each stays a clean, portable
reference.
