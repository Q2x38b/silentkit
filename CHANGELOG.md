# Changelog

Notable changes to the SilentKit skills. Newest first.

## 2026-10-24

Lessons distilled from live anticheat testing folded into the three skills.

### silentkit-modules
- **§3 Silent aim** — added the consistency rule *"act on the rotation you actually send, not the one you're easing toward."* A module that checks "on target / reachable?" against its desired aim point but fires on the still-easing sent rotation acts where it isn't looking (aura hits off-target, clutch places against the wrong face). Gate every server action on the wire rotation; for life-or-death placement, rotate-first with an emergency fallback.
- **§3 Silent aim** — added *"keep the server rotation near the camera while moving"*: cap the aim FOV (~55°) and track fast enough that the sent rotation doesn't lag, so movement reconciles even with correction on. (Correction *off* is the worst case.)
- **§6 Timing realism** — double-clicks now called out as belonging in *every* click mode, not just a humanized one: a perfectly double-click-free burst is itself a signature, so fold a few genuine doubles into plain fixed-CPS mode too.
- **§9 Anticheat threat model** — added three live-tested lessons: some detectors (anti-knockback) can only be *spread out* with a Chance gate, not removed; latency is a hard floor you can't fake (a ping/timer spoof trips the timer check); keep the sent rotation both on target and near the body.

### silentkit-runtime
- **§8 Dev/testing harness** — added the localhost control/telemetry bridge pattern: a dev-only loopback HTTP server that exposes the live config + a filtered anticheat-flag feed and accepts a whole config at once, turning the tune loop into a closed, automatable cycle. Gated strictly to dev/non-production builds.
- **§7 Teardown checklist** — added closing dev-only sockets/servers on uninject so a re-inject can rebind the port (and so the old loader stays collectable).

### silentkit-interface
- **§10 Composition checklist** — added the settings-design lesson: collapse overlapping boolean toggles that answer one question at different strengths into a single ordered enum, showing each dependent sub-setting only for the mode that uses it; migrate old config keys.

## 2026-10-22

- Initial public release of the three skills: `silentkit-interface`, `silentkit-modules`, `silentkit-runtime`.
