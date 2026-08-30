# Authorized native-Linux Phase 0 receipt (2026-08-30)

This directory retains the successful full Phase 0 gate output from a new,
detached clean checkout of `fix/phase0-gate-validation` at commit
`b932a935e0a9438a4d47383f77367146fcefaee6` (tree
`5c2b93d5bc94187ae4471f5006e43c17ad218526`). The pinned Phase 0 toolchain,
a new Cargo target directory, and a new output directory were used for:

```text
CARGO_TARGET_DIR=<new-target> tools/run_phase0_gate.sh full <new-output>
```

The command completed with exit code 0 on one native Linux host.
`gate-summary.json` is the verbatim emitted `latent.phase0.gate.v3` receipt. It
records `status: "pass"`, `authorization_status: "authorized"`,
`phase1_authorized: true`, and an empty `blockers` array. It also deliberately
records `production_ready: false` and `phase1_api_compatible: false`.

The calibration, profiling, and resource-soak packages were measured from the
clean, pushed source commit `52ac47542a05c0a1263f78a14c04a5c2e6b761f3`
(tree `cac3ececdbd0b5734691c30c0283fccff169a5f5`) and are retained in the
corresponding [`calibration`](../../calibration/native-linux-2026-08-30-52ac4754/),
[`profiling`](../../profiling/native-linux-2026-08-30-52ac4754/), and
[`soak`](../../soak/native-linux-2026-08-30-52ac4754/) directories. The gate
defaults and those transport-safe packages were retained at commit
`7acf0736e98bd4343641b0ea49acc7bca709a1b9` (tree
`e918f75428199918a877f4a767eb0b6348dc5f5c`) before the gate ran at the commit
recorded above. The gate
independently reassembled their sharded archives, checked their manifests and
raw records, regenerated their aggregates, and bound each package to the
current checkout through the common canonical execution-evidence identity:

```text
sha256:84d0f64d5661e74ed1dd74e0f4421be8a3ee35740f85aa110775305fcd6e929b
```

The freshly built `phase0-baseline` collector was 137,715,192 bytes with SHA-256
`b11f17f4b78e710b14dfc1f7fd26ecc26853307cf82bf7e12da7ae9cc376e7d3`.
The full baseline passed all 20 required hard checks and retained the required
success, failure, recovery, resource-reclamation, and clean-shutdown outcomes.

The large baseline JSON is retained losslessly as
`baseline/raw-results.json.zst`. The digest in
`baseline/raw-results.json.sha256` is for the decompressed `raw-results.json`;
`receipt.manifest.sha256` checks every other retained payload and explanatory
file. `baseline/BASELINE.md` and `gate-summary.json` are copied verbatim from
the successful run.

This authorization is intentionally narrow. The measurements are
observational and single-host; no cross-machine performance claim, production
readiness, production SLO, capacity guarantee, or Phase 1 API compatibility is
asserted. Later commits may rely on this receipt only while their canonical
execution-evidence identity remains exactly equal to the value above.
