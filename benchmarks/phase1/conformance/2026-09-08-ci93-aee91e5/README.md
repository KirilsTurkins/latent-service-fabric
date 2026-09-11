# Retained PR #93 deterministic CI evidence

These are byte-exact copies of the two downloaded artifacts from
[CI run 34221947356](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/34221947356).
All six PR checks passed. The executed synthetic merge source is
`aee91e53432e4cbb070ee3f2d2d882b1853fe179`, tree
`f717a2f31c4bf4d0bebe0ae1079874d171307b4c`, with `source_dirty=false`.
It is distinct from the final repository merge commit.

Both original artifact directory names and every internal relative path are
preserved. The [file manifest](files.manifest.json) binds all 312 downloaded
files plus the unchanged [independent review](INDEPENDENT-REVIEW.md): 313 files,
1,869,906 bytes. The package-local attributes prevent line-ending conversion;
the ignore override retains original log files. These rules do not rewrite the
receipts. The review's original `target/phase1/ci93-evidence` paths refer to the
same directory layout retained here.

| Evidence | Result | Attempted Invokes | Commands | Recorded duration |
| --- | --- | ---: | ---: | ---: |
| [Conformance](phase-1-bounded-conformance-aee91e53432e4cbb070ee3f2d2d882b1853fe179/run-_kg8prun/conformance.json) | 19/19 required cases passed | 54 | 151 | 24.846 s |
| [Smoke scale](phase-1-measurement-smoke-aee91e53432e4cbb070ee3f2d2d882b1853fe179/smoke-rkqwlynh/scale-01/summary.json) | passed | 0 | 38 | 0.170910701 s |
| [Smoke soak](phase-1-measurement-smoke-aee91e53432e4cbb070ee3f2d2d882b1853fe179/smoke-rkqwlynh/soak-01/summary.json) | passed | 24 | 57 | 2.534501862 s |
| [Smoke benchmark](phase-1-measurement-smoke-aee91e53432e4cbb070ee3f2d2d882b1853fe179/smoke-rkqwlynh/benchmark-01/summary.json) | passed | 85 | 225 | 5.958540920 s |

Conformance used 22 adapter attempts/44 commands and 32 process attempts/107
commands, below its aggregate 64/256 limits. Measurement smoke has separate
bounds; the existing owner suites are not included in that 64-attempt count.
All three measurement categories have one smoke process, so their
[aggregate](phase-1-measurement-smoke-aee91e53432e4cbb070ee3f2d2d882b1853fe179/smoke-rkqwlynh/aggregate.json)
remains `status=incomplete`. Every retained report keeps full Phase 1 completion
incomplete. These are deterministic/tooling checks, not full-scale evidence or
calibrated resource/performance observations.

The recorded environment is Linux x86_64, kernel `6.17.0-1022-azure`, AMD EPYC
7763 with four visible logical CPUs and Microsoft virtualization, Rust/Cargo
1.97.1 and Wasmtime 47.0.3. CI recorded and cross-associated binary/fixture
digests. The downloaded artifacts do not contain the collector executable, so
retention does not claim an independent local rehash of those executable bytes.

The semantic conformance validator and measurement aggregate replay passed again
after retention, with the expected source and current Cargo lock digest. The
conformance/suite/aggregate schemas and all 152 raw JSONL row schemas passed.
The original and retained file bytes and every manifest hash matched. No build,
collector or guest execution was repeated.

From the repository root, with the pinned Python dependencies installed:

```sh
package=benchmarks/phase1/conformance/2026-09-08-ci93-aee91e5
conformance="$package/phase-1-bounded-conformance-aee91e53432e4cbb070ee3f2d2d882b1853fe179/run-_kg8prun"
smoke="$package/phase-1-measurement-smoke-aee91e53432e4cbb070ee3f2d2d882b1853fe179/smoke-rkqwlynh"
python3 tools/validate_phase1_conformance.py "$conformance/conformance.json" \
  --artifacts-root "$conformance" \
  --expected-source-commit aee91e53432e4cbb070ee3f2d2d882b1853fe179 \
  --cargo-lock Cargo.lock
python3 tools/validate_phase1_evidence.py --aggregate "$smoke/aggregate.json"
```

The lockfile check deliberately fails if the supplied lockfile no longer matches
this receipt. The [completion review](../../../../docs/phase-1-completion.md)
keeps this CI evidence separate from the full measurements and the controlled
historical/current comparison.
