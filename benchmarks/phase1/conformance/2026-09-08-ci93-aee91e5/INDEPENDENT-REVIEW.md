# Independent PR93 CI evidence review

**Result: validated.** No collector, guest workload, Cargo or Docker command was run, and no receipt/source file was changed.

Both downloaded artifacts bind CI source commit `aee91e53432e4cbb070ee3f2d2d882b1853fe179`, tree `f717a2f31c4bf4d0bebe0ae1079874d171307b4c`, and `source_dirty=false`. Conformance plus all three measurement process identities agree. Their Cargo.lock digest is `sha256:4fef007f3c6b800f845659d62a319334a1e7428efc0e3fecc7182c88b9cc6669`, independently matched to the current lockfile.

| Artifact / run | Result | Invoke attempts | Commands | Recorded duration |
| --- | --- | ---: | ---: | ---: |
| Bounded conformance `run-_kg8prun` | 19/19 cases passed | 54 | 151 | 24.846 s |
| Measurement smoke `smoke-rkqwlynh`, scale | passed | 0 | 38 | 0.170910701 s |
| Measurement smoke, soak | passed | 24 | 57 | 2.534501862 s |
| Measurement smoke, benchmark | passed | 85 | 225 | 5.958540920 s |

Conformance work partitions exactly into adapter 22 Invokes/44 commands and process 32/107. Its duration is the recorded profile elapsed time; measurement durations are raw footer elapsed times, not parent launcher timing. The smoke benchmark retains 189 metric populations; scale and soak retain seven and eleven respectively.

The semantic conformance validator passed with the expected CI source and current Cargo.lock. Measurement aggregate replay regenerated all statistics from its hashed suite/raw files, verified fixture metadata and per-run identities, and checked matching parent PID/start-time/reap/output-closure plus inner/parent cleanup receipts. All raw measurement summaries report clean shutdown. Structural schemas also pass for conformance, suite, aggregate and all 152 measurement JSONL rows.

All three smoke category groups are passed with one process each. The aggregate remains `profile=smoke`, `status=incomplete`, `phase1_completion=incomplete`; soak reclamation is observational. Bounded conformance also retains `phase1_completion=incomplete`, and every heavy item remains `not_run` with reason `outside-bounded-profile`. Neither artifact is full scale/soak/calibration evidence.

Recorded environment: Linux x86_64, kernel `6.17.0-1022-azure`, Rust/Cargo 1.97.1, Wasmtime 47.0.3. Measurement identities explicitly record Microsoft virtualization, AMD EPYC 7763 CPU model and four visible logical CPUs. No native-host equivalence or Phase0 causal delta is inferred.

## Exact downloaded file identities

Paths below are relative to their artifact run directories under `target/phase1/ci93-evidence`.

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| Conformance `conformance.json` | 413399 | `8001a15308df62db12cd49b7e2dc967ab5f5aae8ae5610ed932a37f722d40cd5` |
| Measurement `aggregate.json` | 151508 | `cd099860a3a7ca34a0e04236fa9eb76e7d8afe24ae0ff0777eae9a5517852663` |
| Measurement `suite.json` | 13881 | `56022c06b2248169c8702e74a1a447d4e75b517d70c10293c92ea3149da13b20` |
| `scale-01/measurements.jsonl` | 23421 | `15d78da7463850e36d618c345aebdcfb3eef636816a1045108bdaa4c1357fd8f` |
| `soak-01/measurements.jsonl` | 35160 | `d6dd0176786cb88e1337efff64bd1fd4ff7c562d5e3e85f31719f819994760f8` |
| `benchmark-01/measurements.jsonl` | 139625 | `4954eb792d52a4801b48994645365dbe7af398cc1a9ceb26283b2baec4f2f7db` |

Downloaded artifact names:

- `phase-1-bounded-conformance-aee91e53432e4cbb070ee3f2d2d882b1853fe179/run-_kg8prun`
- `phase-1-measurement-smoke-aee91e53432e4cbb070ee3f2d2d882b1853fe179/smoke-rkqwlynh`

Executed validators: `tools/validate_phase1_conformance.py` with `--expected-source-commit` and `--cargo-lock`; `tools/validate_phase1_evidence.py --aggregate`; and the repository Draft 2020-12 schemas using the isolated pinned Python dependencies. Binary/fixture digests recorded by CI were retained and cross-associated; unavailable collector executable bytes were not independently rehashed on this host.
