This is an unchanged functional debug recovery collector result, used only for
semantic parser tests. It is not release or paired benchmark evidence. The
identity remains explicitly `functional-debug-only`; the original dirty source
capture and actual process/executable receipt are retained in the two functional
receipts. No binaries are executed during replay tests.

The candidate executed 61 offers and 125 commands. The gzip decompresses to the
original 751,933 bytes, SHA-256 `c17ddbcc394af28f7114ab33ca9bcdd18c74116787d85fae8e1d75519007e168`.
The control gzip is also unchanged: 694,996 bytes, SHA-256
`208e09f8052c5a2716e8b1cf7005cc0485853f776c8d37f9de649c973922de68`.
Its separate functional source/process receipts identify clean control `666e1bb`.
It retained all 61 offers and 125 commands despite losing cell capacity; the
absence of a supervisor observation is unavailable, not a zero counter.
The three publication metadata documents are identical between these graphs.
The complete original
attempt remains in the ignored development evidence directory.

Tests regenerate reference hashes after each mutation so a rejected graph must
fail semantic checks, rather than merely fail a stale file checksum. Historical
budget fixtures and published evidence are unchanged.
