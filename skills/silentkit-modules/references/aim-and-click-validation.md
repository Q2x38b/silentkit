# Aim and click troubleshooting rules

Use when refining the humanization engine, aim assist or click scheduling. These are correctness and validation tips;
adding statistical variation is not proof of an anticheat bypass. Numerical examples elsewhere in the skill are
tuning examples, not detector thresholds guaranteed across servers.

## Aim: repair state and time before adding noise

- Track camera momentum separately from estimated target motion. On target identity change, teleport/discontinuity
  or a meaningful tracking gap, seed fresh target samples rather than differentiating across two different targets.
  A large target switch divided by one frame can otherwise look like enormous target angular velocity.
- Convert fixed per-frame filters to elapsed-time coefficients: `alpha = 1 - exp(-dt/tau)`. For stochastic drift,
  scale decay and innovation consistently with time. A 0.6/0.4 filter or fixed AR walk runs at a different physical
  rate at 30, 60 and 240 FPS.
- Retain angular momentum through ordinary target-point changes and walking→fishing transitions, but reset stale
  velocity and fractional mouse counts after ownership changes, long stalls and world changes. Do not integrate a
  catch-up batch after a stall or impose a minimum frame `dt` that over-advances state at high FPS.
- Bound the **final combined** output after feed-forward, overshoot, shake and drift. A cap applied only to the base
  correction is bypassed by downstream additions. Apply disabled-axis constraints last too: “vertical aim off” means
  zero emitted pitch assistance even when Shake is enabled.
- Quantize every emitted camera/server contribution through one mouse-count path with carried fractional counts.
  A second quantizer or an independent fractional click-jitter path can defeat the first one's contract. Keep the
  last actually sent rotation separate from the desired/eased rotation.
- Clamp drifted/led candidate points to the actual permitted hitbox and revalidate occlusion/reach. Translating the
  hitbox itself by drift can produce a “Closest” point outside the target. A soft on-target zone with entry/exit
  hysteresis is often more useful than continually pulling toward one center point.
- Keep a valid target unless a competing score improves materially; invalidate immediately on death, removal or
  changed filters. Cache candidates at a bounded cadence while revalidating the chosen target per frame.
- Global humanization settings need explicit semantics. Audit private random sources so a supposedly global level
  does not leave whole click/aim paths unaffected. Avoid stacking independent noise to conceal a deterministic bug.

## Clicks: every subclick has current prerequisites

- Recheck eligibility immediately before the primary click, assist click and pending second/double click. A double
  scheduled while active must not fire after mouse release, a menu, focus loss, item use, target/charge invalidation,
  aura takeover or a new player/world session.
- Click Assist should share the configured In Range / On Crosshair / Aim Ready gates instead of bypassing them.
  Cancel pending work when those gates fail; enabling again must not release a stale second click.
- Keep a testable timing state and monotonic clock. Make units explicit at the deadline assignment:
  `nowNanos + milliseconds * 1_000_000L`, not `nowNanos + milliseconds`. A separate cooldown can mask a units bug in
  normal use, so test the deadline independently.
- Make optional double-click, fatigue and rhythm models explicit. Do not force doubles into every mode on the
  premise that every real mouse produces them. Configured CPS endpoints should retain their meaning; measure
  generated, cancelled and consumed clicks separately, and never emit an unlimited catch-up burst after a stall.
- A per-tick action budget is a design choice for a particular module/sequence, not a universal vanilla rule.
  Diagnose actual ordering, action types and version-specific behavior before treating a count as a violation.

## Useful test matrix

Use seeded randomness and a fake monotonic clock for stationary/moving targets at 30/60/144/240 FPS, irregular frames,
stalls, yaw wrap, switches, occlusion, teleports, pitch limits, sensitivity and ownership changes. Assert final bounds,
zero disabled-axis output, in-hitbox points, no stale estimator after yielding and no queued click after invalidation.
Test key release and menu opening between paired clicks. Keep pure arithmetic, production-adapter tests and in-game
feel/packet traces separate; one does not establish the others.
