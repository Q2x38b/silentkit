# Automation: state, menus and shared controls

Use for inventory helpers, item sequences, fishing/selling loops, background operation and module cancellation.
These are reusable rules of thumb from implementation and review; they are not a claim that every consuming client
already implements them or that a server accepts the resulting automation.

## State and ownership

- Bind deferred work to `{owner, player, world/session, prerequisites, expiry}`. Re-enabling a module starts a new
  engagement; it must not resume an old click, throw, message or slot return. A world change invalidates work even
  when the connection and player UUID survive.
- Treat enable as a transaction: if initialization fails after acquiring a key, timer or claim, roll it back and
  leave the module disabled. Count consecutive tick errors, reset the count after success, and use a bounded failure
  policy rather than logging forever while controls stay owned.
- A rotation claim can be refused. Return an explicit result and stop dependent actions when ownership is lost.
  Recheck the claim and the held item immediately before a delayed use. Give independently cancellable modules
  distinct owner tokens.
- Camera, movement, primary attack, secondary use, hotbar selection and packet rules are separate resources. Winning
  camera ownership is not permission to click or overwrite another movement producer.
- Temporary hotbar swaps are leases. Restore only if the original owner still controls the expected selected slot
  in the same session. A user's manual selection cancels restoration. Disconnect drops the lease without touching
  the next player's inventory.
- Shared graphics settings need one baseline and prioritized overrides. Independent snapshots make disable order
  restore an intermediate module value. Preserve user edits observed while an override is active.

## Inventory clicks and merchant menus

- Bind a click plan to the actual screen instance, menu instance/ID and player/world. A different container with
  the same title is not the same transaction. Cancel when scope changes, the screen closes or the module stops.
- Revalidate source slot, destination and cursor stack before **each click**, including the second/third click of
  a swap. Budget actual clicks, not queued lambdas; a single lambda can contain several server interactions.
- Match merchant actions by normalized item/component display text, with material/layout information as supporting
  evidence. Do not assume “the chest is always slot N” or that a decorated GUI title identifies every phase.
- Opening a menu, transferring items, requesting sale and observing completion are separate phases. A successful
  right click is not proof that the next menu arrived, nor that the server accepted the sale.
- Some custom sell menus reject shift-click transfer. An explicit pickup/place sequence with cursor checks is a
  useful fallback. Retry only after checking whether the source changed and whether the item is already deposited;
  otherwise a retry can pull the item back out or carry a stack into the next menu.
- Speed up transfers with a small configurable click budget and acknowledgement-aware progress, not an unbounded
  burst. Track partial stacks, a full destination, rejected clicks and the cursor separately. Revalidate before
  pressing Sell; stop depositing before transitioning to confirmation.
- Destructive cleanup needs a concrete item scope. For “spare inventory/hotbar armor,” exclude equipped armor,
  offhand, Elytra and non-armor unless the user chose otherwise. Recheck the trash menu before inserting items and
  close only that menu afterward. A sale finishing does not authorize unrelated destructive actions.

## Placement before dependent actions

- Carry one immutable `{target, support, face, hitPoint}` candidate through planning, alignment and execution.
  If varying the in-face point, sample once and reuse it. Pre-aiming at the center and clicking fresh jitter can make
  the action disagree with its own readiness test.
- Reach alone does not establish visibility. Check the actual candidate ray, replaceability, held item and ownership
  at action time, and try alternate valid neighbors before declaring the target unreachable. A full-sturdy-face
  filter is a conservative policy, not proof that every partial block surface is unclickable.
- `consumesAction()` can mean opening a furnace or another interactive support. Distinguish attempted, predicted and
  confirmed placement; a successful right click is not proof that a block went down. Handle secondary-use policy
  explicitly rather than incrementing a clutch placement count for a consumed GUI interaction.
- A rotate-first emergency timeout starts with the **current attempt**. Using time since a previous successful
  placement, initially zero, can make the first attempt an immediate emergency and skip alignment entirely.

## Fishing and navigation

- Model `find water → approach → settle/aim → cast → fish → capacity check → merchant → deposit → sell → cleanup →
  reacquire water`. Use completion observations and bounded timeouts between phases, not one chain of fixed sleeps.
- Keep a hysteresis band around “inventory nearly full” so a changed stack does not alternate fishing and selling.
  Pause fishing before walking/interacting, and account for an outstanding bobber/cast before leaving.
- After selling, search from the **current** position. The old fishing spot is a candidate, not an obligatory
  destination; a nearer reachable shore can be better.
- Water proximity alone does not establish a safe fishing stance. Check a dry standing surface, body/headroom,
  an unobstructed cast and the surrounding bank. Aim at a reachable water surface rather than straight down at the
  nearest block. Ease from walking yaw/pitch into the fishing pose through the shared camera controller.
- A two-block bank can trap a swimming player in an endless jump loop. Search for an exit compatible with real
  step/jump height, use collision-aware routes, and bound no-progress attempts. Replan another exit or pause with an
  actionable status instead of retrying the same impossible jump indefinitely.

## Menus, focus and background work

- Inventory movement should explicitly allow supported container screens and reject focused text input. Typing W,
  A, S, D or Space in chat, a sign, a book or a search box must not silently become movement.
- Background mining is an owner-specific policy: focus-loss pause and held-attack capture checks may be relaxed for
  the active miner while explicit user-opened menus still pause its controls. Avoid changing the user's global pause
  preference to accomplish this.
- If camera work runs per frame, unfocused FPS throttling changes the controller's opportunity to update. A bounded
  background frame floor can help, but respect the user's cap, use elapsed time and discard stall catch-up.

## Useful checks

Exercise menu A→B, same title/new menu ID, cursor changes between clicks, disable/re-enable, disconnect/rejoin,
manual slot changes, competing aim owners, rejected transfers, partial sales, full trash menus, lost NPCs, focus loss
and unreachable banks. Use fake senders/click adapters for these tests; a unit test does not need to sell or trash
real inventory.
