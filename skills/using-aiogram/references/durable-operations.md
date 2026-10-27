# Durable Telegram operations

Use this reference when an existing bot queues work, resumes after restart, or retries
Telegram mutations. These are application patterns, not aiogram services. A small
stateless handler does not need a new queue or database. Preserve the project's storage,
permissions, and delivery policy; introduce infrastructure only within the agreed scope.

## distinguish rejection, acknowledgement, and uncertainty

Cancelling a task or timing out locally does not prove that Telegram rejected its request.
For a non-idempotent send/create/add/delete, reason about the operation's evidence:

| Evidence | Recovery decision |
|---|---|
| Rejected before the effect, with method-specific evidence | Preserve progress and schedule a bounded safe retry if the error is transient |
| Successful API response durably recorded | Resume after that effect; a later metadata read or cosmetic cleanup failure must not repeat it |
| Request may have reached Telegram, but no acknowledgement is recorded | Reconcile using the operation's evidence, or stop with an explicit unresolved outcome |

Where the application needs durable recovery, persist intent before the request and
checkpoint the successful response immediately afterward. A crash between success and
checkpoint remains an uncertainty window. Do not promise exactly-once delivery where the
method supplies no usable idempotency key; document the chosen at-most-once/best-effort
policy and its possible missing or duplicate result.

Reconciliation must account for concurrent external edits. A different count, title, or
item position does not negate an acknowledged add. Conversely, finding a remote object
with the intended name after a lost create response does not prove that this operation
owns it. Never adopt or delete it without sufficient ownership evidence. Temporary upload
identities can differ from final media identities after Telegram processing.

## admission, ownership, and checkpoints

- Validate owner, source kind, schema/revision, and target at both handler and worker
  boundaries. A guessed draft ID or hidden button is not authorisation. Persist only the
  serialisable context needed to resume; do not put raw user content in diagnostics.
- Claim before effects: select eligibility and change ownership atomically in storage,
  not with an unlocked read followed by an update. Fence progress, reschedule, completion
  and cleanup against the current worker/claim token so a stale task cannot overwrite a
  successor. A callback cache claim prevents duplicate admission; it does not replace remote-effect recovery.
- For multipart work, freeze the source revision/order and record acknowledged parts
  and the resume cursor with consistent meanings for uploaded and cached media paths.
  Resume at the first unacknowledged part. Preserve validated preparation and upload
  handles across requeues; retain their workdirs until terminal cleanup.
- Track result delivery separately from ancillary instructions, status deletion, and
  analytics. A failed follow-up must not resend or revoke the successful primary result.
  Log delivery is best-effort unless the application implements a stronger contract.
- Settle reservations and related claims on the terminal transition, including jobs
  cancelled before their worker starts; worker-only cleanup never runs for those jobs.
  Make settlement idempotent and operation/owner-fenced, and run the same repair during
  recovery. Release only proven-unused reservations; preserve ambiguous effects.
- Revalidate expiring permissions, drafts and time-window quotas immediately before the
  first effect, after cooldown/queue waits. Atomically pair the current reservation with
  intent. A queued admission is not permanent authorisation; an acknowledged or ambiguous
  effect must not be reassigned to a new quota period merely because recovery crossed it.

## pacing and bounded recovery

Pass structured retry metadata through wrappers without converting it into a generic
failure. A worker should checkpoint and schedule the next eligible attempt, releasing its
slot instead of sleeping through a long FloodWait. Use durable deadlines when restart
must preserve the wait; an in-memory monotonic timestamp is not a persisted deadline.

Share cooldowns only across the verified affected scope and reserve proactive pacing
before requests. Do not treat a chosen interval as a guaranteed Telegram limit. Rate
deferral, planned pacing, transient execution failure, and an ambiguous effect need
different recovery decisions; blanket retry decorators hide those distinctions.

Even `TelegramRetryAfter` supplies a delay, not an idempotency key. If the mutation path
can raise after remote acceptance, retain intent and reconcile before repeating. Textual
retry descriptions need the narrow, method-aware classification described in
[errors](../../aiogram-errors/SKILL.md#reading-telegrambadrequest).

Bound resume by deadline and lack of progress. A per-attempt timeout is an execution
budget, not proof that all work failed. Checkpoints, counters, and retained artefacts
must survive the same recovery path, without silently resetting the retry budget.

## cancellation and shutdown

Arbitrate cancel and final delivery intent/ACK in the same storage transaction under the
current ownership fence. A separate pre-check followed by an awaited cancel write races
with delivery. Persist accepted cancellation before calling `task.cancel()`; the worker
must then be unable to claim delivery. An accepted cancel forbids a result. If delivery
intent already won, reject or defer cancellation under an explicit in-flight policy;
never report both guaranteed cancellation and successful delivery. Define the outcome
for an already acknowledged result; do not advertise an immediate guaranteed undo.
An ambiguous remote effect requires reconciliation before retry or destructive cleanup.
Only verified task-owned artefacts can be removed by a compensating operation.

Cancellation must not interrupt required rollback/settlement halfway through. Retain and
drain any owned shielded cleanup task before returning or releasing its connection;
`asyncio.shield()` alone lets the caller exit while cleanup is still running. Repeated
cancellation must not leave a shared connection in a transaction or release a successor's
reservation. Bound cleanup and retain recoverable evidence when it cannot complete.

Heavy rendering belongs outside the polling event loop. Cancelling an asyncio wrapper
or a running executor future does not stop the underlying CPU work. If cancellation must
stop it, use the application's owned process/descendant lifecycle and wait for it to end
before deleting its workdir. Retrieve late executor failures; do not switch a broken
process task into the event-loop thread as a hidden fallback. Choose an explicit process
start context suitable for a multithreaded runtime rather than inheriting unsafe locks.

Shutdown stops admission/schedulers first, drains or checkpoints owned work and final
notifications, then closes storage and the Bot session. Keep exclusive runtime ownership
until old workers can no longer act. Do not blindly replay every interrupted job at startup.

## verify the boundary you changed

Use existing local tests with real storage transitions and fake Bot API responses. Inject
the failure at the relevant point: before a request, after simulated acceptance, after
acknowledgement but before notification, or during cancellation/recovery. Check exact call
counts, cursor/owner state, and no mutation for invalid ownership. A successful fake send
does not establish Telegram acceptance, rate limits, client rendering, or production
readiness. Live checks require the user's authorised scenario and controlled artefacts.

## API references

- [aiogram response classification](https://github.com/aiogram/aiogram/blob/v3.31.0/aiogram/client/session/base.py)
- [Telegram response parameters](https://core.telegram.org/bots/api#responseparameters)
- [Python executor cancellation](https://docs.python.org/3/library/concurrent.futures.html#concurrent.futures.Future.cancel)
