# Attach and reload: practical failure-handling tips

Use when improving a developer injector, shipped bootstrap, bytecode engine or uninject path. These are architecture
recommendations and fault cases discovered through source review and isolated probes. They are not a claim that a
particular implementation already satisfies them, or that an injector is invisible to external inspection.

## Success needs an acknowledgement from the right stage

- Returning from `loadAgent` proves the agent entry point returned, not that a queued game-thread startup or resource
  reload succeeded. Report `READY` only after initialization, required hook installation and resource completion.
- Give each attempt an ID and explicit phases: `VALIDATING`, `PREPARING`, `PATCHING`, `STARTING`, then `READY`, or a
  terminal `FAILED`, `CANCELLED`, `RESTART_REQUIRED`. Do not infer readiness from a free-form “patched N classes” log.
- Catch asynchronous startup and resource-reload failures at their completion boundary, publish the failure and run
  idempotent rollback. An outer agent-thread catch cannot see an exception merely logged inside a queued task.
- A polling timeout is a timeout, never “Injected.” Bound the overall operation as well as individual stages: a poll
  beginning after a blocking attach returns is not an attach deadline. Use an appropriate worker/process boundary
  where cancellation of an in-process blocking operation cannot be established safely.
- Publish complete status snapshots atomically if using files; tolerate incomplete reads without inventing terminal
  results. Keep per-attempt state, bounded logs and sanitized exception chains rather than one ever-growing static log.

## Verify coverage, not just valid bytecode

- Build a version-specific required-hook manifest: target class, method descriptor, instruction anchor, expected
  minimum/maximum matches and optional-integration status. Preflight required hooks before enabling actions.
- A hook engine can return verifier-valid bytes with **zero** matched instructions. Record planned, inserted and
  installed hooks separately. Honor required match counts; a required missing target must fail the attempt.
- A transformer exception may leave the original class unchanged. Counting successful returns from
  `retransformClasses` does not prove transformation coverage. Propagate required generation/patch failures out of
  diagnostic-only lists and into rollback/status.
- Verify late-loaded targets as well as classes loaded at attach time. Test the exact hook names at the expected
  methods, not merely that some `invokedynamic` exists somewhere in a transformed class.
- Prefer bounded verifier diagnostics in memory/logs. Generated class dumps are an explicit opt-in debugging artifact,
  not a default failure side effect. A dump from another build is not evidence about the current artifact.

## Restore first; release the runtime when safe

- Independently guard cleanup steps: a failed settings save must not skip module shutdown, key release, packet
  cancellation, worker termination, socket closure or resource removal. Aggregate failures and continue cleanup.
- Maintain a cleanup stack for resources acquired during startup; it should also handle a partially initialized
  client whose “active” flag was never set. Cancellation invalidates queued work using the attempt generation.
- Distinguish disabled/stopped from fully restored. If even one changed game class fails restoration, do not clear
  all hook state, close the disposable loader and announce a clean uninject regardless of that failure.
- Linked constant call sites may retain old method handles and their defining loader; unresolved sites may still
  need registry bytes. A loader close does not erase classes or invalidate those handles. Retain a safe disabled
  bridge for residual hooks or report restart required and block a new injection into incomplete restoration.
- Other transformers can affect restoration. Reconcile with JVM retransformation behavior and test supported loader/
  renderer combinations instead of blindly redefining saved originals over everyone else's changes.
- Resource providers, pipelines and framebuffers have ordering dependencies. Remove owned pipelines before resources
  they reference. A full reload during world rendering can race renderer targets; prefer a safe game-thread boundary
  or deferred reload, and rebuild renderer targets through the supported version's resize path when needed.
- Dropping references only makes class unloading/GC possible. Neither `System.gc()` nor closing a loader guarantees
  immediate collection or memory erasure. Include surviving threads, listeners, lambdas, handles and side tables in
  leak investigations.

## One bootstrap, fresh implementation loaders

- Dynamic agent entry classes are normally loaded through the system class loader. A newer jar with the same agent
  class name does not replace an already defined class. Repeated dev injection can refresh the client while keeping
  an old transformation engine. Validate this against the target JDK source/runtime.
- Keep a small versioned bootstrap/bridge permanent, and load implementation/engine code in fresh owned loaders per
  attempt. Use the same direct `inject(bytes, options, credentials, instrumentation)` handoff shape for local and
  downloaded builds. Avoid publishing payload bytes or credentials in JVM-wide properties or command-line arguments.
- Parent the client loader to the actual game loader. Resolve only owned implementation packages child-first under
  per-class locks; keep game, JDK and stable bridge identities shared. Test stale parent definitions and mixed dev/
  shipped paths. Named-module opens/exports/read edges must cover the **new** child modules that need them too.
- Record bootstrap ABI, engine build ID, payload hash and game version separately. An incompatible permanent bridge
  needs a clear restart requirement; compatible client-only changes should remain reloadable.

## Targeting and delivery tips

- Resolve companion boot jars relative to the running injector's code source, not the payload's arbitrary directory
  or the terminal's current directory. Test absolute-path invocation from an unrelated working directory.
- Use process names/classpath as discovery hints, then verify the actual game version/loader through the bootstrap.
  Validate an explicit PID too. Ask for a PID or present choices when several matching instances exist rather than
  choosing the first. Read embedded build metadata; a renamed jar filename is not compatibility evidence.
- Check target Java/classfile version, instrumentation capabilities, class modifiability and bridge ABI before
  changing game state. Redact launch tokens on candidate/error paths as well as the selected-process happy path.
- Verify the bytes actually loaded. Hashing a separate bundle while loading an unchecked neighboring jar is not
  payload verification. For shipped delivery, retain authenticated encryption, expected digest and allowed-origin
  checks; local builds need explicit provenance/build metadata rather than pretending a local hash is a signature.
- Bound expanded entry size, total expanded bytes and entry count, reject duplicate names and validate required
  metadata. A compressed/encrypted download size limit alone does not bound ZIP expansion in the game JVM.

## Useful fault tests

Use a fake `Instrumentation`, generated fixture classes and temporary loaders for missing required anchors,
transformer failures, partial restores, stale parent collisions, nested attempts, cancellation before queued startup,
resource completion failure, a cleanup step throwing, timeout/no terminal result, duplicate ZIP entries and unsupported
ABI/capabilities. Test actual supported game classfiles with the production engine as a separate layer. Finally test
live inject→use→uninject→reinject when authorized, including worker/socket cleanup and renderer compatibility.

A probe asserting a known defect is audit evidence; once fixed, replace it with a desired-invariant acceptance test.
Report source review, fixture reproduction, bytecode verification and live round trips separately. None alone proves
complete launcher compatibility or anticheat acceptance.
