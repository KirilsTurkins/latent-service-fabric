# Native Linux Phase 0 authorization receipt (2026-08-29)

This directory retains the full receipt emitted by a separate clean checkout of
`fix/phase0-gate-validation` at commit
`54d02679aff757d4bf25d16e088b32d45682cb7f` (tree
`b77e4efa1cd46628efcbfebed6e3b0c05feade28`).  The command was:

```text
make phase0-gate
```

It completed with exit code 0 on a native Linux host.  `gate-summary.json`
records `status: "pass"`, `authorization_status: "authorized"`,
`phase1_authorized: true`, and an empty `blockers` array.

The fresh calibration, hot-path profiling, and resource-soak evidence was
measured at commit `a724a5e35234175f1001d1983e4411296ffa6b78` (tree
`c06ace2ae0f503495fa5bf87710ae5fc74c7ef50`).  The receipt verifies that its
canonical execution-relevant identity matches this checkout:

```text
sha256:d9ec14a46695eb2afedc07b70b114686163f82a0cfc216f65c521c541ad44191
```

The retained raw archives and manifests are in the corresponding
[`calibration`](../../calibration/native-linux-2026-08-29-a724a5e3/),
[`profiling`](../../profiling/native-linux-2026-08-29-a724a5e3/), and
[`soak`](../../soak/native-linux-2026-08-29-a724a5e3/) evidence directories.
The large baseline result is retained losslessly as
`baseline/raw-results.json.zst`; its decompressed `raw-results.json` is
checked by `baseline/raw-results.json.sha256`.  The other gate output files are
copied verbatim.  `receipt.manifest.sha256` checks every retained receipt file.

This authorization does not change the receipt's separate `production_ready`
or `phase1_api_compatible` fields, which remain `false`.
