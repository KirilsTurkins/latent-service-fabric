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
