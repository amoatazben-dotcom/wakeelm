# Cost estimates and budgets

Prices are provider-reported per-token values; absence of a price is UNKNOWN. Free means FREE_VERIFIED/FREE_REPORTED catalog evidence, not a guarantee of the provider's future billing. Estimates use input/output tokens and those prices. Token-priced calculations remain estimates; `actual_cost` stays null unless actual billing evidence exists. The platform does not claim estimated provider pricing is a paid invoice.

Before each model call PostgreSQL reserves tokens and an estimated cost under row/advisory locks. Unknown prices reserve a conservative $0.10, visibly labelled as a reservation. Completed responses reconcile known estimates from server-side provider usage. Failed/uncertain calls retain conservative reservations. A worker crash cannot erase spent or reserved budget. Idempotency keys prevent duplicate ledger identities.

Job budgets cap model calls, steps, total tokens, estimated cost and duration. All fallback/specialist attempts count. Restart loads prior tokens/calls and the job's durable estimated spend. Daily global/provider, daily user and monthly user spend are server gates. Known unusually expensive job estimates produce a Telegram warning before queueing; execution still stops at quota or budget. No billing integration is required.
