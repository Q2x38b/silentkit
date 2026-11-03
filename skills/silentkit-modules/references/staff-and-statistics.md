# Staff evidence and mining statistics

Read for a staff detector/list or a mining/currency telemetry backend. The interface skill owns presentation; this
reference defines what the data actually means.

## Staff detection: evidence, not universal vanish detection

- Combine the data the client already receives: listed profiles, received-but-unlisted profiles, loaded player
  entities, team rank metadata, recent attributed chat and recent profile removal. Share one collector/classifier
  between alerts and the HUD instead of running inconsistent scanners.
- Normalize formatting codes, Unicode width/small capitals and separators before **whole-word rank** matching.
  Match rank metadata, not arbitrary substrings of a username. Sidebar/fake team holders and generated team names
  can look like player names; require suitable identity/rank evidence before promoting them.
- Prefer UUID identity, then carefully scoped names. Do not merge conflicting real UUIDs by name. Exclude self,
  support exact watched and ignored identities, and let ignore override watch/heuristic matches. Reevaluate ignores
  after a display/name change rather than preserving an old positive forever.
- Attribute chat through sender metadata/signatures where available; the message body mentioning “admin” is not
  staff identity evidence. An ordinary invisible or spectator player is not proof of staff or vanish.
- Separate actionable states such as nearby/loaded or observed online from uncertain ones such as unlisted profile,
  team-only membership or recently left tab. Hidden status can be suggested only by received evidence; a completely
  server-hidden player who supplies no packets cannot be discovered by passive client logic.
- Weak evidence needs a minimum observation period, explicit expiry and bounded history. Persistent offline team
  membership should not keep refreshing an “online staff” alert indefinitely. Debounce confirmations, apply per-identity
  cooldowns, and treat reappearance separately from a constant finding.
- Keep automatic disconnect off unless configured, and require strong confirmed evidence for it. An uncertainty
  label must not silently become an action trigger. Bound per-scan alerts and aggregate overflow to avoid toast spam.
- Clear collected evidence on connection/world replacement. Network-thread profile-removal callbacks should verify
  their source listener/current session before mutating main-thread collector state. Use bounded maps and expiries.
- Passive collection does not imply permission to probe the server with commands, messages or hidden requests.

Useful checks: decorated ranks vs rank-like usernames; watched+ignored conflicts; UUID/name collisions; genuine vs
unattributed chat; unlisted profiles alone; offline teams that persist; late callbacks from an old listener; self;
evidence expiry; reappearance cooldowns; and weak evidence never causing automatic disconnect.

## Mining and currency rates: know the numerator and denominator

- Keep session totals, a rolling BPS window, session average, a defined peak window, blocks/hour, runtime and free
  inventory slots separate. Count unique local break completions with a short bounded deduplication window; attack
  attempts and aim targets are not mined blocks.
- A locally completed/predicted break is not server-confirmed profit. Name its source and allow for protected blocks,
  replacements and corrections. If server-confirmed telemetry exists, keep it distinct rather than silently combining it.
- Parse scoreboard text with team prefix/suffix and normalized formatting. Support configured label aliases and
  relevant compact suffixes (K/M/B/T and larger suffixes only where defined). Use decimal arithmetic for balances;
  binary floating point can lose small deltas on very large accounts.
- A balance of zero differs from an absent or unparseable balance. On an objective/label/source change, missing-data
  gap, reconnect or world replacement, establish a fresh baseline instead of interpreting the next value as earnings.
- Compute currency/hour from observed balance deltas over a sufficient **observed** time interval. Net balance rates
  include spending, purchases, transfers and rewards; do not label them gross mining revenue without source evidence.
  Hide/warm up unstable rates until the denominator is meaningful.
- Per-block estimates need enough block and currency observations aligned to the same interval. Avoid dividing a
  post-gap balance change by blocks accumulated before that gap.
- Freeze an ended session consistently and reset explicitly on a new session. Track missing time so inactivity or
  unavailable scoreboard data does not silently alter rate meaning.

Useful checks: positive/negative/zero deltas, small intervals, huge balances, styled labels, suffix ambiguity,
missing/reappearing objectives, equal-name replacement objectives, reconnects, duplicate break callbacks and
protected-block predictions. HUD rates are estimates from stated sources, not proof of server payouts.
