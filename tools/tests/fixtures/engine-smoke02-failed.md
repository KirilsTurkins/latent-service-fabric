This gzip contains the unchanged raw JSON from the failed #106 control matrix
smoke02, retained as an oracle regression fixture. It is not qualified benchmark
evidence. All 52 offered Invokes, transport failures and original failure flags
remain present. No identity, request, result or clock field was rewritten.

Original source: ignored `target/phase1-extension/issue106-matrix-smoke-02-control-raw.json`.
Expanded bytes: 582,470. SHA-256:
`f02088348773dde6a5d2f221ab9a80dc2a73c45a32f4492d1eea622085a5b6d3`.

The tests use its actual successful first context response and matching source
ledger to check WIT option encoding and inner versus outer deadline identity.
They separately prove the failed arm remains unqualified and its old rounded-up
caller deadline cannot pass the corrected conservative-floor projection.
