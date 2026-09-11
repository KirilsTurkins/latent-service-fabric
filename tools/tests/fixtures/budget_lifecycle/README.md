These are unchanged functional debug collector results, used only for semantic
parser tests. They are not release benchmark evidence and cannot qualify a
paired suite: both identities explicitly say `functional-debug-only`. Each
diagnostic completed 23 offers and 57 commands. The candidate source is
`9cc06a0fc7bf2fb42ebf6144e2da7e84b03c9869`; the control source is
`822cf84f9e4e1708a8fc4d11d3b1ca641b70dc72`. Each raw document retains its original
executed debug binary identity. The three shared, actual published metadata
documents are retained alongside the compressed raw, which preserves the
original JSON bytes.

The control has four rejected offers that ended before admission without a
terminal-decision observation. Replay preserves that unavailable observation;
it still requires the actual terminal winner and matching retained status.

Tests rehash altered documents before invoking semantic replay. Original
measurement receipts and the earlier failed functional runs are not modified.
