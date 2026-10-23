# SilentKit

**A distilled toolkit for ghost clients.** Three Agent Skills for building Minecraft ghost clients with real
bypasses: behaviour, interface, and loader.

## Install

Add all three:

```bash
npx skills add Q2x38b/silentkit
```

Or pick one:

```bash
npx skills add Q2x38b/silentkit --skill silentkit-modules
npx skills add Q2x38b/silentkit --skill silentkit-interface
npx skills add Q2x38b/silentkit --skill silentkit-runtime
```

## Skills

| Skill | What it covers |
|---|---|
| **[silentkit-modules](skills/silentkit-modules/SKILL.md)** | The behaviour layer: module/event/setting architecture, the humanization engine (eased rotation, mouse-GCD quantization, timing realism), silent-aim with rotation-ownership arbitration, vanilla-physics prediction (fall / flight / projectile sims), aim-control math (PD+I, leading), and combat/world technique patterns. Ships a queryable catalogue at [`references/modules.json`](skills/silentkit-modules/references/modules.json). |
| **[silentkit-interface](skills/silentkit-interface/SKILL.md)** | The UI layer: an in-game floating-panels menu, settings rendering, HUD/overlay system, a custom 2D render abstraction + font pipeline, theming, keybind UX, and an optional web/remote control surface. |
| **[silentkit-runtime](skills/silentkit-runtime/SKILL.md)** | The loader layer: Java agents & Instrumentation, custom classloaders, loading classes from in-memory bytes, disposable-child-loader hot-reload, resource injection, clean teardown, and single-codebase multi-version support. Standard JVM mechanisms only. |

## Using these as Agent Skills

Each `skills/<name>/` directory is a self-contained skill (a `SKILL.md` with YAML front-matter, plus any
`references/`). Drop a directory into your agent's skills folder, or read the `SKILL.md` directly as a design
reference. Nothing here is tied to a specific project, brand, or codebase — API names are illustrative.

## Scope & intent

These are **engineering references** for the architecture of a ghost client — the patterns, the math, the
composition. `silentkit-runtime` deliberately covers only standard JVM loading/reload mechanisms and **excludes
detection-evasion / anti-forensics** material.

## License

MIT — see [LICENSE](LICENSE).
