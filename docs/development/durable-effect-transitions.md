# Durable effect transitions

`latent-effects::dispatch` supplies the checked record/transition port consumed
by the Phase 4 atomic store and shared dispatcher. Each record preserves its
independent authority/intent decoder and command/commit/effect linkage. It stores
one bounded latest receipt and a history sequence; history belongs in separately
bounded, paged rows rather than an expanding inline vector.

Only pending work and explicitly qualified scheduled retries can be claimed.
Store ownership epoch, claim generation and attempt number fence stale workers.
The store persists the send marker before physical dispatch. Restart requires
exclusive new-process ownership and positive proof that the old physical owner
has retired. An interrupted marked attempt becomes uncertain. An unmarked
attempt can be known not dispatched only under that same retirement proof.
Neither lease expiry nor a caller timeout supplies it.

Provider acknowledgement differs from consumer processing. Local commitment
does not mean provider acknowledgement. Uncertain work cannot be rescheduled as
known nonexecution. A qualified retry additionally retains identical payload and
provider incarnation inside a finite deduplication horizon; scheduling beyond
that horizon or resuming too late blocks instead of sending. Captured attempt
limits terminate repeated claims. Concrete transport workers must intersect
attempt deadlines with the retained retry horizon as well as effect expiry.

These are internal checked transitions, not a standalone dispatcher. The actual
store must apply them by durable compare-and-set and persist the returned record
before send. Fixed workers, indexed due-work scans, payload ownership, provider
transport, standalone lifecycle and operator recovery remain required by #391.
Tests cover record/transition schedules only; encoded record round trips are not
engine crash-recovery or provider-delivery evidence. No guest command replay or
application scheduling API is introduced.

```sh
cargo test -p latent-effects --lib --locked
cargo clippy -p latent-effects --all-targets --locked -- -D warnings
```

The registered suite requires nine authority cases and ten dispatch cases.
