# Bounded HTTP response reason metadata

The broker response head can retain an optional raw HTTP/1 reason phrase.
`None` means unavailable; `Some([])` means an actual empty phrase. The retained
I/O buffer reserves its complete capacity, at most512 bytes, until the head is
dropped. Existing result, metadata, host-memory and operation ownership apply.
Controls and DEL reject, with HTTP horizontal tab permitted.

The streaming adapter has an explicit capture selector, currently false on
the existing provider. It captures the pinned Hyper1.11.1 parser's original
reason bytes. Hyper preserves every noncanonical phrase in its extension;
extension absence for HTTP/1 means the parser observed the canonical phrase.
Other protocol versions remain unavailable. The old typed HTTP response and
provider selection stay unchanged. The additive phase-timing provider must
select capture explicitly and expose these bytes through its new response.

Four registered native tests cover actual HTTP/1 parsing of canonical,
custom, empty, non-ASCII and oversized phrases, unavailable HTTP/2 metadata,
complete prepaid capacity retained beyond session close, and refusal cleanup.
They use real accepted broker calls and the original outbound charge. This
source checkpoint has formatting and catalogue checks; native execution and
the new provider's end-to-end qualification remain pending.
