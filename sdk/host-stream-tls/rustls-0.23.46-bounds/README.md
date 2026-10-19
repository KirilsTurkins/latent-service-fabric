# Captured current direct host TLS parser prerequisite

This is the source-only rustls **0.23.46** counterpart of the immutable
[0.23.45 capture](../rustls-bounds/README.md). The provider selects 0.23.46;
`apply_current` requires that exact manifest pin, registry lock checksum,
archive, five preimages, patch document and modified files. It writes a fresh
private tree and never changes the shared registry or the installed provider.
Unknown versions, widened parser bounds and qualification claims are refused.

Four parser preimages match 0.23.45. The 0.23.46 `conn.rs` contains upstream
changes; this capture preserves every byte except propagating the bounded
deframer's error at its one existing call. The same certificate, authority,
extension and fragment limits apply before excess parser work. The allocation
reference is byte-identical, including the original 5,000-certificate
amplification witness, its old-source failure and the eight bounded vectors.
Upstream license texts remain available [beside the original capture](../rustls-bounds/).

The optional reference command selects this source explicitly with
`--parser-version 0.23.46`; its default remains the historical 0.23.45 profile.
Source authentication and data-only controls do **not** establish that the Rust
reference, TLS handshake or signed component executed. `ACCOUNTING_QUALIFIED`
remains false, production installation stays disabled, and the original 256 KiB
connection / 64 KiB trust reservations are unchanged. Fresh current-closure
allocation, stack/kernel, protected lifecycle and actual-component evidence is
required before enabling direct host TLS. This is a prerequisite for #738;
#739/#740 and language-owned guest TLS retain their independent requirements.

## Current minimal reference lane

The `Current host TLS parser reference` workflow builds only two small parser
executables: the authenticated original 0.23.46 source and the captured bounded
source. `reference-Cargo.lock` fixes 24 registry dependencies to the exact
versions, sources and checksums in the maintained workspace lock. The qualifier
checks that closure before creating output, optionally fetches only the locked
closure, then builds both references offline and locked with two build jobs.
It checks that neither build changes its lockfile.

The original 5,000-certificate case must still exceed the 64 KiB parser ceiling
and fail its reference process; the bounded source must pass all eight existing
vectors with zero live parser allocations after Drop. The workflow retains the
closed observations, source/lock identities and build diagnostics. A green lane
would establish only this native parser reference, not complete connection or
trust accounting, a TLS handshake, or a signed component. Historical 0.23.45
receipts are not replaced or re-attributed.

## Distinct provider dependency

`latent-streams` now aliases the local `latent-rustls-outbound` package under
`crates/vendor/rustls-outbound`. The package is excluded from workspace test
targets, not from source authentication. `PROVIDER.json` binds all 119 upstream
files, the five captured parser changes, the sole Cargo package-name change,
and all three original license texts. The library name, dependency/feature
options, build script and public API source remain upstream except for those
five parser changes. `tools/host_stream_tls_provider.py` reproduces the tree
from the same checksum-pinned archive and refuses mixed, extra or altered files.

The vendored upstream `Cargo.lock` remains immutable source evidence; the
workspace lock is authoritative for normal builds. Upstream dev/test targets
are not enrolled as workspace tests.

The selection uses ordinary Cargo path resolution. It does not patch crates.io,
change unrelated HTTPS dependencies, mutate a registry, or require a prebuild
repair. TLS peer fixtures explicitly keep ordinary upstream rustls types.
The exact native inventory case retains the fork's authenticated license texts
and derivation identity. CI accepts this one excluded dependency only after
full source verification; all other unknown paths remain refused.

This source selection is not an executed provider qualification or permission
to install TLS. `ACCOUNTING_QUALIFIED` remains false. The
[current accounting plan](../../../docs/runtime/outbound-stream-host-tls-accounting-plan.md)
keeps allocation, stack/kernel, lifecycle and signed observations separate.
