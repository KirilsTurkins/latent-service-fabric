# Current Java restore collector continuation

This continuation belongs to PR #970 and issue #718. PR #968's accepted value
captures and frozen-ABI child refusal remain separate evidence.

The collector selects current version-2 restore roots explicitly. It copies
stopped signed release/control catalogs into a fresh private data directory,
excluding the original state and checkpoint. Coupled source hardlinks become
independent copied custody. The native recovery owner creates the restored
`dataDirectory/state` and separate protected checkpoint; the collector sets
`createIfMissing` to false and retains every provider, credential, quota and
store limit. Historical version-1 `stateRoot` selection remains unchanged.

Current restore requests include the original manifest digest and distinct
checkpoint destination. Migration resume supplies the original migration
operation, stage view and protected checkpoint identities through the current
`resume-migration` action. No generic resume approves a retained migration.

Path-dependent installed profiles require new current authority. A read-only
full-installation inspection supplies observations. One explicitly bounded
version-2 session with an empty operation list performs the authenticated
policy and provider-binding updates; it installs no command target or effect
dispatcher. Each existing generation is read once and frozen with the exact
input bytes before any update. Changed bytes or an uncertain mutation stop
the sequence without retry. Six ordinary node sessions remain the limit.

The current budget field is `maximumEffectCount`; its original ceiling remains
one. The collector identity includes both new restore custody modules.

86 focused source controls passed. They cover real filesystem custody and
synthetic policy sequencing, not installed schema migration or restore
qualification. Current recovery reports, installed HTTP captures and the
actual signed campaign still require the combined native gateway and peer.
No ticket closes and no authority is inferred from copied data or inspection.
