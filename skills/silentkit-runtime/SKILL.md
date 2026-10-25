---
name: silentkit-runtime
description: >-
  Engineering reference for the runtime/loader layer of a JVM ghost client: Java agents and Instrumentation,
  custom classloaders, loading classes from in-memory bytes, a disposable-child-loader hot-reload pattern, resource/
  asset injection, clean teardown, and single-codebase multi-version support (a Compat facade with cached
  MethodHandles + a runtime version constant). Standard JVM mechanisms only — this skill deliberately excludes any
  detection-evasion / anti-forensics material. Brand-neutral and framework-agnostic.
---

# SilentKit · Runtime

How a ghost client is loaded, hot-reloaded, and kept compatible across engine versions — using **standard,
well-documented JVM mechanisms** (the same ones debuggers, profilers, APM agents, and hot-reload frameworks use).

**Scope note (read this).** This skill covers the *engineering* of loading and reloading code on the JVM and of
abstracting version differences. It does **not** cover evading detection, hiding from memory/AV/anticheat scanners,
anti-forensics, or "leave no trace" techniques, and it should not be extended in that direction. If a task is about
making a load *undetectable* rather than about *loading or reloading* code, it's out of scope — the clean-teardown and
GC-hygiene material below is about not leaking memory and leaving the process runnable, nothing more. Module-level game
techniques live in `silentkit-modules`; the UI layer in `silentkit-interface`.

---

## 1. Java agents & Instrumentation

The JVM's supported entry points for touching already-loaded code:

- **`premain(String args, Instrumentation inst)`** — runs before `main`, via `-javaagent:agent.jar`. The manifest
  declares `Premain-Class` (and `Can-Retransform-Classes`, `Can-Redefine-Classes` as needed).
- **`agentmain(String args, Instrumentation inst)`** — runs after startup, loaded through the **Attach API**
  (`com.sun.tools.attach.VirtualMachine.attach(pid).loadAgent(path)`). Manifest declares `Agent-Class`. This is the
  path a dev-time injector uses to attach to an already-running game.
- **`Instrumentation`** gives you: `addTransformer(ClassFileTransformer, canRetransform)`, `retransformClasses(...)`,
  `redefineClasses(ClassDefinition...)`, and `appendToSystemClassLoaderSearch(JarFile)`. A `ClassFileTransformer`
  receives each class's bytes at load/retransform time and returns modified bytes (use ASM to edit).

This is the backbone of any load-time code modification on the JVM. A **fileless handoff** is clean here: the injector
hands the agent its payload through an in-memory/local channel (e.g. a byte buffer the agent reads on attach) rather
than writing a jar to disk, which is simply fewer moving parts and no temp-file cleanup — not an evasion technique.

### 1a. The attach-inject sequence (what `agentmain` actually does, in order)

The agent is tiny and references **no engine classes itself** (so it loads before/independent of the game's state).
Its job, in order:
1. **Find the loader that holds the engine.** Probe candidate loaders for a known engine class (Mojang-named), as in
   §3a — that loader becomes the parent of the child loader.
2. **Make the client's classes loadable** — build the `Map<String,byte[]>` from the handed-in jar bytes and construct
   the child loader (§3a) over them.
3. **Start the client on the engine's main thread**, not the attach thread — reflectively call the client entry point
   (`bridge.start()`), scheduling it onto the game's tick/executor so it initialises on the right thread with the
   render/ tick context live.
4. **Apply the mixins last**, once the client is up, by running the inject-time mixin engine (§5) over the already-
   loaded target classes. Order matters: the client's systems must exist before hooks start firing into them.
Pass the agent a small options string (`jar=<path-or-handle>;status=<file>`) and have it write a **status file** the
injector polls, so the external injector UI can report success/failure without a socket.

### 1b. Two-agent boot handoff (one code path for dev and production)

The production injector has the decrypted client **bytes in memory**; a dev injector has a **jar on disk**. To avoid
two inject code paths that drift, load **two agents**: a tiny **boot** agent first that only *publishes the bytes*
(from the injector's buffer in prod, or by reading the dev jar *inside the target JVM* in dev) into a known holder
(a system property or a static field in a host-loader class), then the **client** agent that reads that holder and
runs the sequence above. The real inject logic is identical in both modes — only the trivial boot agent differs.

---

## 2. Classloaders & loading from in-memory bytes

- A classloader turns bytes into `Class<?>` via the protected `defineClass(name, byte[], off, len)`. Subclass
  `ClassLoader` (or `URLClassLoader`) and override `findClass` to serve classes from a `Map<String, byte[]>` you hold
  in memory — no file on disk required. Delegate to the parent for everything you don't own (standard parent-first),
  or go child-first for classes you want to shadow.
- **Package/resource access** — serve non-class resources (configs, assets) from the same in-memory map via
  `getResourceAsStream`. Keep your classes in their own package namespace to avoid clashing with host/engine classes.
- **Linking order** — define a class only when first needed (lazy `findClass`); resolve dependencies through the same
  loader so your module graph is self-consistent. Watch for classes that must be defined by a *specific* loader (the
  one the host/engine resolves against) and route those accordingly instead of your child loader.

---

## 3. Hot-reload via a disposable child loader

The clean pattern for "swap the implementation without restarting the process":

1. Create a fresh child `ClassLoader` whose parent is the host/app loader.
2. Load the new version's classes into it from the in-memory byte map.
3. Hand control to the new instance's entry point; register its hooks.
4. To reload: tell the current instance to **tear down** (unregister hooks, dispose resources, stop threads), drop all
   references to the child loader, and let GC collect it — then repeat from step 1 with the new bytes.

Keys to making it GC-clean (so you don't leak a loader per reload):
- Route all hooks/listeners through a **stable host-side registry** (a `HookHost`) the child registers into and that
  the teardown fully clears. A single dangling listener pins the whole child loader in memory. The host-side registry
  and a tiny **bridge interface** are the *only* types defined in the host loader; everything else lives in the
  disposable child.
- Stop every thread the child started; cancel every scheduled task; close every resource.
- Don't let host-side static fields (or engine singletons, event buses, resource managers) hold child-loader objects
  past teardown. Enums, lambdas (they capture their defining class), and registered callbacks are the usual leaks —
  audit them. A heap dump after a few reloads should show one live child loader, not N.

A tiny "host bridge" interface (defined in the host loader, implemented by the child) is the clean handoff point: the
host calls `bridge.start()` / `bridge.stop()` and never otherwise reaches into the child. `stop()` doubles as both the
reload teardown and the uninject teardown, so there's one correct shutdown path.

### 3a. The disposable loader in detail (the parts that are subtly hard to get right)

A production version of this is more than "new URLClassLoader." The pieces that actually make it work across repeated
reloads:

- **Parent = the game's loader, not the app/system loader.** The child's parent must be whatever loaded the engine
  (Minecraft), so the client resolves engine + library classes normally. Find it at inject time by walking up from a
  known engine class's `getClassLoader()` (e.g. `Class.forName("net.minecraft.client.Minecraft", false, systemLoader)`
  across candidate loaders — a launcher-agnostic agent probes for the loader that actually holds the Mojang-named
  classes, which works on vanilla / Fabric / Quilt / Forge / NeoForge / Lunar / Feather alike as long as names aren't
  obfuscated).
- **`registerAsParallelCapable()`** in the child loader's static init — the game loads classes on many threads; a
  non-parallel loader serializes (and can deadlock) under that.
- **Define classes lazily, transform on define.** Don't eagerly define the whole jar. Override `findClass` to define
  each `dev/yourclient/**` class from the byte map on first use, and run your **class transformer in that same step**
  (e.g. rewrite accessor / duck-interface call sites to `invokedynamic`, see §5). One code path defines-and-rewrites,
  whether a class loads now or an hour into the session.
- **Split "disposable" from "permanent."** A few infra classes must **survive** a reload/uninject — the host bridge,
  and a small **stable runtime** package your rewritten call sites bind to (the `invokedynamic` bootstrap methods, any
  shared enum the host holds). Define *those* into the **host/game loader** (permanent), and everything under your
  client package into the **child** (disposable). If a bootstrap method the game's own code now links against lived in
  the child, dropping the child would break already-linked call sites. This split is the single most common thing
  people get wrong.
- **Dropping the loader frees the code *and its string constants*.** Because the client's classes live only in the
  child, uninject collects the classes and the interned/constant strings with them. That's *why* per-class string
  obfuscation is loader-local and why a leaked reference (which pins the loader) also keeps your plaintext in memory —
  a reason the teardown audit matters beyond just "no restart."
- **Hidden classes for generated hooks.** Code you generate at inject time (per-target mixin hook classes, §5) should
  be defined as **hidden classes** via a full-privilege `MethodHandles.Lookup` on a host class that lives in the child
  loader *and the same package* (`defineHiddenClass` requires the hidden class share a nest/package with its lookup
  class). That lands the generated hooks in the disposable child (collectable) with private access to your mixin
  members, instead of polluting a real package name.

---

## 4. Resource / asset injection

To add your own assets (textures, shaders, fonts, lang) to an engine that loads from resource packs: implement the
engine's resource-provider / pack interface backed by your in-memory map and register it as a high-priority pack, then
trigger a resource reload. Keep the provider version-adapted behind the Compat facade (§6). Unregister it on teardown
and reload again so nothing of yours lingers (also so the engine doesn't try to recompile pipelines against assets that
are about to disappear).

---

## 5. Bytecode hooks: transformers vs a mixin framework

Two ways to insert hooks (tick/render/packet) into engine methods:
- **A mixin framework** (compile-time, annotation-driven `@Inject`/`@Redirect`/`@ModifyVariable` against named
  signatures, applied at class load). Proven, concise, great tooling. Prefer this where available.
  **The inject-time catch (the detail that trips people up):** a mixin framework applies at class *load* time, but an
  attach-time inject goes into an *already-running* game whose target classes (`Minecraft`, the local player, the
  connection) are **already loaded** — so the framework's own transform never fires for them. The clean answer is **one
  mixin source, two apply paths**: the dev run uses the framework at load time, and the injected build ships its **own
  small mixin engine** that applies the *same* mixin classes to the already-loaded targets via `retransformClasses`.
  Such an engine supports what the client actually uses — `@Inject` (HEAD/RETURN/TAIL/INVOKE with ordinal+shift),
  `@Shadow`, `@Accessor`, duck interfaces, and mixin-added fields — by turning each mixin's handlers into **statics in a
  hidden class**, accessors/ducks into `invokedynamic`, and added fields into a **side table** keyed by instance (you
  can't add a real field to a loaded class). Keep the **original bytes** of every retransformed class to restore on
  uninject. The client code just declares mixins; only the engine touches bytecode.
- **Load-time ASM/Javassist transforms** (a `ClassFileTransformer` that edits target methods at runtime). More work and
  more fragile, but needed when no mixin framework is available or when you must support obfuscated targets.

Keep hooks thin: fire an event, let modules handle it. Version-branch only the few hooks whose target *signatures*
differ (see §6) — the common case is that one hook body serves every version and only the `@At` target or a single
field access changes.

---

## 6. Single-codebase multi-version support

Two models:

**A. Compile-per-version (recommended for a few adjacent versions).** A preprocessor (e.g. Stonecutter) with `//?`
comment branches builds one artifact per version against real named types — full type-safety, IDE support, and a proven
mixin framework. A hand-written **Compat facade** covers the handful of APIs whose shape changed. Cost: N artifacts to
build/ship.

**B. One runtime artifact across many versions.** Detect the version once → an int; keep per-version name-remap tables;
a mapping/wrapper layer resolves every engine member by reflection and branches on the int; load-time transforms stand
in for mixins. This exists to bridge **per-version naming differences across many loaders** — only worth it when you
target *many* versions and are willing to leave a mixin framework behind. It trades away compile-time safety for one
jar.

**The pragmatic middle (do this).** Stay on model A, but make the Compat facade carry the divergence:
- **A packed runtime version constant** baked per build (e.g. `MC = 2602` / `2603` from a `//?` branch, or parsed once
  from the engine's version string), with `atLeast(packed)` / `below(packed)` helpers, so non-mixin logic can branch at
  runtime and live in the common sourceset.
- **A thin static method per changed API**, its body `//?`-branched so one call site (`Compat.swing(...)`,
  `Compat.clockTicks(...)`, `Compat.readRgba(...)`) compiles correctly on every target. Everything else stays
  version-agnostic. Pure renames/moves can instead be resolved with **cached `MethodHandle`s** in a static initializer
  so a single compiled body serves both versions with no source branch at all.
- Keep mixins compile-time; only where a hook's target **signature** differs do you branch it. A packet or render hook
  whose field names/types changed across versions is the usual case — branch just that method's body.

```java
// Compat facade sketch: a packed version constant + one branched body per changed API.
final class Compat {
  //? if >=2603 {
  /*static final int MC = 2603;*/
  //?} else {
  static final int MC = 2602;
  //?}
  static boolean atLeast(int packed) { return MC >= packed; }

  // One call site; the body is version-branched so both builds compile:
  static void swing(Object entity, Object hand) { /*? if >=2603 {*/ /* new API */ /*?} else {*/ /* old API */ /*?}*/ }

  // Pure rename resolved once, no source branch:
  private static final MethodHandle CLOCK = resolve(/* candidates per version */);
}
```

**A decompile-diff discovery workflow** finds the divergences cheaply: decompile the two target versions, diff the
classes your hooks and facade touch, and only the methods that actually changed need a `//?` branch. Prefer published
name-mapping tables over re-decompiling when you only need the renamed member.

---

## 7. Teardown checklist (leave the process as you found it)

- Unregister every hook/listener from the host registry.
- Stop every thread; cancel every timer/scheduler; await their exit so none fires mid-teardown.
- Remove your resource provider and reload resources.
- Strip any pipelines/registries you added so the engine doesn't try to recompile against your (now gone) assets.
- Drop all host-side references to child-loader objects (static fields, engine singletons, event-bus registrations,
  captured lambdas) so the loader is collectable; verify with a heap dump across several reloads.
- Close any dev-only sockets/servers (e.g. the §8 control bridge) so a re-inject can rebind their port — a bound
  loopback socket held by the old loader is both a port clash and a reference that keeps that loader alive.

Clean teardown is what makes repeated hot-reload viable, and it's what lets an uninject return the process to a plain
unmodified game — it's good engineering regardless of context, and it's the one and only correct shutdown path shared
by reload and uninject.

---

## 8. Dev / testing harness

How to iterate on the *behaviour* without shipping a build to users each time. **Scope (unchanged from the top):** this
is developer tooling — compiling, attaching, and reading your own diagnostics — not detection evasion. The one piece
that touches anticheat is a *diagnostic that measures your own packets against a legit baseline* so you can tell what an
in-game server anticheat would flag (§module-skill topic); that is in scope. Hiding the loader from the OS/AV is not.

**The fileless re-inject loop (no game restart).** The whole point of the disposable-child-loader pattern (§3) is a
tight edit→build→see loop against a *running* game:
1. **Build** the client jar (per engine version, so the artifact name carries its version — `…+<ver>.jar`).
2. **Attach** with a small dev injector that uses the **Attach API** (`VirtualMachine.attach(pid).loadAgent`). It
   auto-picks the running JVM whose engine version matches the jar — probe each candidate's `sun.java.command` /
   classpath for a version segment — or takes an explicit pid; and it **redacts** session tokens/access tokens out of
   any process name it prints (those leak in launch commands).
3. **Hand off the bytes.** The shipped injector streams decrypted class bytes into the target and the agent reads them
   from a system property. For dev, a tiny **first** agent (loaded *before* the client agent) just reads the dev jar
   from disk *inside the target JVM* and sets that same property — so the real agent's code path runs identically to a
   production inject, with no separate dev branch. Two `loadAgent` calls: boot (set the bytes) then client (inject).
4. **Hot-swap.** The agent defines the client classes into a **fresh child loader**, applies the hooks, and runs. To
   iterate: **uninject** (a bound key / "panic") removes the transformer, retransforms the game classes back to the bytes
   they loaded with, drops the child loader, clears the per-inject state, and nudges GC — then a **newer** build attaches
   into a *new* loader, no restart. The GC-hygiene of §3/§7 is what makes the Nth re-inject behave like the first.

**Debug hooks, commands and settings.** Keep diagnostics in the code behind cheap gates, not in throwaway patches:
- **Deterministic sim probes** — expose the prediction sims (§4 in the modules skill) as callable debug methods that run
  from state and *return* their result, e.g. `debugPredict()` (the landing the held projectile would produce next tick:
  start/vel/end/ticks/entity) and `debugSimulate(pos, vel, kind)` (run the integrator from an **explicit** spawn state).
  Because the sims are pure read-only functions of `(pos, vel, world)`, they're reproducible from a saved state.
- **A "want vs sent" rotation log** — the highest-value anticheat diagnostic. An opt-in setting ("Flight/aim debug log")
  prints, each tick, what the module *wanted* versus what actually went **on the wire**, plus the mouse-GCD step, and the
  position/velocity. Log it at **two sites**: at the autopilot/aim code (the *want*), and again at the outgoing
  move-packet hook (the *ground truth*, after every other system has written the rotation) — logging `rot` versus the
  heading implied by your velocity (`atan2(-vx, vz)`) is exactly how you catch the classic "look doesn't match
  movement" flag (elytra, silent aim, strafe) before a server does.
- **System-property toggles** for throwaway experiments without a settings row: e.g. a packet-log that prints each
  delayed packet and how long it was held (validates §11 ordering/age), a look-log that prints per-frame view-vs-target
  (measures turn smoothness), render-self flags (draw your own ESP / nametag / silent rotation in third person so you can
  *see* where the server thinks you're aiming), and a "treat a dummy entity as a player" flag to test player-only visuals
  on a summoned stand.
- **Patch-failure dumps** — when a hook fails to apply to an already-loaded class, dump the rewritten bytes and run the
  framework's verifier, so a broken mixin is diagnosable from the log instead of a silent no-op.
- **A localhost control/telemetry bridge — the biggest iteration win.** A dev-only HTTP server bound to `127.0.0.1`
  inside the running game turns the edit loop from "toggle 20 settings by hand, read chat, repeat" into an automatable
  one: `GET /state` returns the live config export + player state **and a ring buffer of recent chat lines filtered to
  anticheat flags**; `POST /config` applies a whole config in one shot (marshal onto the main thread). Because the game
  and your tooling share the machine, a script (or an agent) can push a setting change, you perform the in-game action,
  and the script reads back exactly which checks tripped — a closed tuning loop with no GUI. Keep it strictly dev-only:
  **gate it so it never runs in the shipped/production-injected build** (e.g. off whenever the production loader flag is
  set), bind to loopback only, and have it `stop()` in the teardown path (next item) so a re-inject can rebind the port.
  It reads *your own* client state and the chat *you* already see — it is diagnostics, not evasion.

**Deterministic simulation testing.** The reliable way to trust a prediction sim: run it from an explicit `(pos, vel)`
with a debug method, then **summon the real projectile/entity with that same pos+velocity** and compare where it actually
lands against the sim's predicted landing. A match validates the integrator's constants and per-axis collision order; a
divergence localises the wrong constant (a drag, a gravity, an axis-order bug) because the input state was fixed. The
same approach tests the fall/pearl/wind sims — fix the start state, compare predicted vs observed — and it's repeatable
precisely because the sims never mutate world or entity state.

---

## 9. Protection & auth (the paid-client layer)

If the client is a paid product, gating *who* can inject and *what* they get is its own layer — standard software
licensing/DRM, separate from the loader. (This is access control, not anti-forensics: hiding the loader from the OS,
anti-debugger traps, and tamper watchdogs are out of scope here.)

- **Auth before inject.** The injector signs the user in first — a browser **device flow** (PKCE: the desktop app shows
  a code, the user approves it on the site, the app polls with a private verifier) yields a **session token**. No valid
  token, no inject. Bind the session to the machine with an **HWID** so one account isn't shared endlessly (a device
  cap). Redact the token everywhere it could print (it leaks in process args and logs).
- **License gate on the server, not the client.** The inject/payload endpoint checks the account has an **active
  license** (subscription current, key not expired/revoked, account not disabled) and only then releases the payload.
  Do the check server-side with the session token — a client-side "am I licensed?" flag is trivially patched.
- **Encrypted delivery.** Ship the real client bytes **encrypted** (e.g. AES-256-GCM), authenticated to the session,
  decrypted **in memory** by the injector and handed to the agent (§1b) — never written to disk. A dumped jar from a
  pirate is then ciphertext, and the plaintext only ever lives in the injected JVM.
- **Over-the-air updates.** Each build is a versioned, encrypted release the server hands out; the client has no
  self-update (the bytes arrive decrypted from the injector), so "update" means re-inject. A small handshake version
  (`protocol`) lets the server refuse an outdated injector cleanly instead of failing deep in the inject.
- **Live kill-switch + dead-man's switch.** A lightweight heartbeat lets the server end a session mid-run (key revoked,
  licence lapsed) → the client uninjects itself. Pair it with a **fail-closed** rule: if the client can't reach home for
  a grace window (someone firewalled the domain to dodge a revoke), it uninjects anyway. Cutting the cord is the trigger,
  not an escape.
- **Casual-extraction slowdown (legit).** Name-obfuscation (rename-only ProGuard) + per-class string encryption on the
  *shipped* jar keeps API endpoints and messages out of a trivial `strings`/decompile. It only raises the bar against a
  casual dump — anything in a JVM you control can ultimately be inspected — and it must survive the inject path (verify
  an in-game inject after enabling it; string-encrypting the whole client can silently break runtime behavior).
