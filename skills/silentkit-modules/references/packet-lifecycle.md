# Packet delay: ordering and lifecycle tips

Read for Blink, FakeLag, BackTrack, knockback delay or a shared packet service. These contracts address queue bugs;
they do not make delayed traffic inherently accepted by a server. Prefer the target version's actual protocol and
local primary sources over packet names copied from an older client.

## Useful invariants

- Bind entries to the originating connection and session generation; include world/player generation where their
  contents depend on that state. Outgoing replay must not use whichever connection happens to be current.
- Clearing a concurrent queue is not sufficient cancellation. A producer can pass its old-connection check, pause
  during disconnect cleanup, then enqueue after the clear. Invalidate generations and serialize lifecycle changes
  or revalidate atomically enough to reject that stale enqueue and dispatch.
- Use a monotonic sequence for arrival order and release boundaries, and a monotonic clock for durations. A release
  cutoff based on wall-clock milliseconds can include packets enqueued **after** the command in the same millisecond.
  Reset session-scoped cutoffs and last-sent/correction metadata at cleanup.
- Distinguish `HOLD`, `ORDERED_PASS`, `FLUSH_BEFORE_PASS` and, only where semantically safe, `IMMEDIATE_CONTROL`.
  Returning zero from a rule is not an exemption if the queue automatically holds every later packet behind its head.
  In particular, a keepalive behind an indefinite incoming hold prevents the client from generating its response.
- Treat disconnect/configuration and respawn/world replacement as explicit barriers. A listener object may survive
  dimension/player replacement. Drain applicable old-state packets before the barrier or discard them according to
  semantics; checking listener equality alone cannot prevent stale-world entity updates.
- Keep protocol batches intact. Modern movement may be followed by a per-tick end marker. If a movement-only hold
  lets that marker through a flush-on-live path, the backlog is flushed every tick. Inspect both actual tick emission
  and the classifier, including explicit game-version differences.
- Keep actions, container state, prediction acknowledgements, keepalives and teleport/configuration control traffic
  out of arbitrary movement holds. Define whether order requires draining earlier movement before a live action;
  do not bypass everything just because its own delay is zero.
- Publish owner+rule consistently. Owner-checked release prevents a disabling module from clearing another's rule;
  it does not by itself synchronize in-flight producers or combine independent incoming queues correctly.

## Replay, backpressure and observation

- Scope outgoing replay bypass to `{receiver, exact packet, one-use token}` and restore the previous token in
  `finally`. A thread-wide boolean can also exempt unrelated nested sends. Dispatch incoming packets through the
  game's supported listener path on the appropriate thread, with acceptance and generation checks.
- Preserve callback/flush semantics. A discarded queued write still needs a documented completion/cancellation
  outcome; dropping a packet while leaving its promise unresolved can hang a caller.
- Bound count, age and where practical estimated retained bytes, with an explicit overflow policy. An optional
  Auto Send toggle is not a global bound. Do not translate queue-age settings into “cannot flag” claims.
- Separate attempted, queued, dispatched and dropped counters. A send hook before cancellation sees attempts, and
  replay may visit that hook again. Count an actual dispatch once for its connection/session and reset observability
  baselines when ownership or sessions change.
- If multiple incoming queues are needed, specify the ordering dependency they preserve and merge by sequence.
  Do not assume a timestamp can prove causality, or that every entity packet can be delayed independently of later
  entity removal/reuse, world replacement and protocol state.

## Good reproduction cases

Use fake dispatch/clock collaborators and latches to exercise: keepalive behind an indefinite hold; a producer
paused across disconnect clear; same-listener world replacement; tick-end markers; same-timestamp release boundaries;
nested sends; callback completion on discard; correction followed by new movement; disable while held; and queue
overflow. A probe that asserts today's **faulty** outcome is audit evidence, not an acceptance test. Replace it with
the desired invariant when fixing the code. Keep fixture results, actual transformed class verification and live
connection behavior clearly distinguished.
