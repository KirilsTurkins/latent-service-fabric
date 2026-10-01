# Bounded logical recovery snapshot

`latent_state::recovery::snapshot` exports one MVCC view of the selected
transaction engine. It streams each logical family in key order, preserving
original state, namespace operation receipts, commands, results, inbox and
outbox bytes. It does not copy a live database file or execute a provider.

The first profile requires every namespace to be quiesced and no retained native
read view. The offline control owner must also drain actual command, dispatch,
acknowledgement and maintenance owners before opening the exclusive source
root. These blocking routines run on that owner's existing fixed storage
workers. A descriptive namespace flag is insufficient proof of physical drain.

The closed manifest records the storage format, exact runtime digest, operator
and operation identity, source namespace bytes, schema and history epochs,
installed retained-work decoder identities, linked inventory and required
immutable artifacts. Installed row owners must validate actual cross-row and
payload closure in the same view and collect original publication/schema
associations. A schema declaration cannot substitute for a decoder. Missing
artifacts or a removed decoder refuse the snapshot before export begins.

Bounds are 65,536 rows, 128 MiB of logical data, a 160 MiB stream, 128 namespaces,
128 required artifacts and a 1 MiB manifest. Export scans at most 128 rows and
4 MiB per page; inspection allocates at most one 4 MiB row plus bounded metadata.
The original deadline is at most one minute and is checked throughout both
operations. Capacity exhaustion refuses; it never trims history or payloads.

Inspection checks framing, family identities, key order, all lengths before row
allocation, installed row codecs, canonical closed metadata, source namespace
bytes, counts and both manifest and stream digests. Truncation, unknown formats,
duplicate fields and trailing bytes produce no usable receipt. Restore must
additionally validate the complete staged view before its guard can leave
`Staging`; stream integrity alone does not establish logical completeness.

Snapshots contain sensitive business data. The protected offline wrapper owns
an explicit private operator destination, exclusive creation, named-file
fences and fsync. Neither backup data nor credentials belong in repository or
public benchmark artifacts. The current codec tests exercise actual embedded
snapshots and adversarial inspection. Protected fresh-root restore, reconciliation
and normal management integration remain separate qualification requirements.
