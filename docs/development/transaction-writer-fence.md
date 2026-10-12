# Atomic writer acceptance and coherent engine pages

`EmbeddedStore::apply_fenced` is the host-internal publication boundary. The
engine validates every expected row, stages every family mutation, and checks
row and byte capacity inside one physical redb writer transaction. It then
invokes one short host callback immediately before durable commit I/O. The
callback rechecks current policy, publication, namespace lifecycle and
cancellation, and consumes the host's once-only commit acceptance. It must not
perform I/O, guest work or blocking waits. Policy locks cover acceptance only;
they do not cover the engine flush.

`FencedStoreError::Fence` proves the callback rejected before commit I/O.
`FencedStoreError::Store` preserves the engine's actual failure classification.
An uncertain commit quarantines writes and requires original-identity recovery.
OCC and capacity failures happen before the callback, so they do not consume
an irreversible host acceptance. The guest cannot call this internal port.

`ReadView::scan_after` returns a bounded page and an optional last-emitted key
for exclusive continuation in that same read view. It includes continuation
only when another matching physical row remains. A first row larger than the
page ceiling returns capacity rather than a falsely exhausted empty page.
Higher layers must bind cursors to tenant, namespace incarnation, transaction,
query and generation; engine positions alone grant no authority.

Three additional engine-backed tests check complete rollback on fence
rejection, OCC/capacity rejection before acceptance, and exact coherent paging
despite a later write. The paging test also checks foreign-prefix continuation,
empty scans and an oversized first row. The complete local state suite passed
19 tests on Windows. Linux validation is recorded separately by the owning CI
suite. Existing engine qualification evidence is unchanged.
