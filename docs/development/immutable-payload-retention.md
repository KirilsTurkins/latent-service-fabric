# Immutable local payload retention

The host can opt an existing local blob root into durable reference retention
with `LocalBlobStore::open_durable` on its admitted native storage worker. The
selected state engine must already have its immutable store identity. A bounded,
durable root record binds that identity and the exact local root configuration.
An ordinary opener recognizes this record after restart and refuses the former
unreviewed whole-object release operation. Existing immediate reads, writes and
S3 behavior keep their existing profile.

`LocalBlobProvider::capture_reference` uses the installed local provider's
existing capability session, open authorization, audit and shared worker. It
verifies the original tenant, digest, media type, length and protected file
identity before returning an affine `CapturedLocalPayload`. The actual native
reader and provisional publication pin stay owned by this value. An S3 version
string or another provider's descriptor cannot construct it. The complete host
still supplies its current policy/publication acceptance fence.

The required ordering is seal, capture the verified physical pin, prepare the
independent owner rows, and publish those rows in the same state-engine
transaction as the business envelope. The physical pin remains alive until the
actual commit attempt and any uncertainty retire. This does not make a database
transaction span the blob filesystem. A failed state snapshot or unknown
ownership refuses reclamation.

State, result, effect and snapshot owners have separate rows and original
generations. The host-derived object index includes exact provider provenance;
the physical index also retains aliases and epochs naming the same protected
local object. A count and generation head changes with both indexes and the
primary rows in the same transaction. Missing indexes, primaries or count heads
are visible storage failures, never evidence that content may be removed. Each
prepared plan reports full referenced payload bytes as well as retained metadata
bytes; the complete coordinator must charge the existing namespace quotas.

Physical release holds the original blob publication guard, requires every
provisional pin to retire, and only then obtains a fresh view from the same
selected state engine. It verifies the store identity, configuration, positive
zero-owner head and empty physical index before writing the existing durable
release marker. Existing readers retain their real file pins until destruction;
the bounded existing maintenance turn cannot reclaim their bytes early.

`CompleteEnvelope::attach_verified_payloads` accepts those actual captured pins
for result and effect owners. It compares the original session, publication,
tenant and selected store, and verifies exact existing inline body bytes and
media type. The new durable attachment closure and independent reference rows
share the original command/result/outbox/inbox transaction and namespace and
tenant quotas. Descriptors never become provider request bytes. The existing
publish method refuses attached pins; `publish_with_payloads` requires the
installed coordinator's explicit current command/effect/provider acceptance
fence. This initial port attaches to matching inline values and does not add
out-of-line state or effect decoding.

Startup validates each attachment closure against its command attempt, format,
result or effect, reciprocal primary/index rows and exact payload digest/media/
length. Missing required owners are visible corruption. The original bounded
result-maintenance owner removes only the expiring response's reference and
updates its durable closure, count head, namespace pin and tenant quota in the
same generation-checked transaction. Pending effects keep their own references
and original command/commit/format linkage. A real reader still prevents physical
release after the last durable response reference disappears.

State replacement/deletion, terminal-effect release, migration/snapshot adapters,
bounded review of sealed orphans that have no owner head, and ordinary installed
runtime composition remain required for #396. Such an orphan currently refuses
release instead of inventing a zero-owner count. These library ports do not
qualify external S3 retention, complete #396, or establish hosted CI or
installed-node evidence. Native execution qualification is recorded separately
for each immutable candidate; source checks alone do not qualify the schedules.
