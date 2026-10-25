# Local-service child registry retirement

The Rust DeveloperTools job's clock and dependency-watch checks passed, but its nested local-service fixture returned `["4214"]` instead of `["4242"]` for two sequential children. The first child's ordinary accounting had settled while the broker registry still retained its paid weak session headers. Those physical guards correctly retained the child's original capacity, so the second delegation could not enter the fixture's one-live-child profile.

The post-Store observer now retires only the original closed registry entry after all calls, waiters, handles, results and buffers are gone and the original session core has no strong owners. Its private Stats identity prevents clearing a reused entry. The removed entry is destroyed outside the registry mutex; actual weak/header destruction still precedes billing refund. Detached work, a live core or an unavailable retirement fence preserves quarantine and the original result.

[Run 40164771308 / job 121083465485](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/40164771308/job/121083465485), executed source `95319ec828adbaa096b89cf7063d2ccb9a5164f9`, passed one new actual native regression, five Python controls and all fourteen original signed Rust scenarios. The native regression covers real original child capacity, retained calls/results, closed-but-live core refusal, registry contention, stale observers and slot reuse. The signed `two-fresh-children` case returned `["4242"]`, with two actual child calls, 17,888 fuel, 2,349,969 reported peak bytes and 7,684 microseconds. These are one observed case's values, not a resource minimum or upper bound.

The original fixture remains two cells, one live child, two live descendants, 1 billion root fuel, 32 MiB root memory, 5 s root wall time and 16 child calls, with the original explicit service-invoke grant and 8 MiB callee memory ceiling. Denial cases keep their original typed inner outcomes and fixture assertions. Both node shutdowns were clean, the callee compiler was reaped and the disposable private pair workspace was purged.

The [bounded public receipt](evidence/local-service-registry-retirement-2026-10-25.json) binds the 467,431-byte artifact 12588241111, all 25 public members/CRCs, 45 exact Git recipe inputs, the complete current Git inventory and 20 raw command channels. The current native case ran in 0.04 s (85.85 s including its Cargo command); the normal Rust tools/node builder took 351.51 s and the original fixture 81.35 s. The three earlier native/config passes remain historical; they were not reexecuted or credited to this changed source.

| Preserved run | Original outcome |
| --- | --- |
| 40142691214 attempt 2 | 13/14 local-service cases passed; exhausted dimension was not recorded. PR head `a6931393c09352d436878ece2bc2fa01a4189bee`; executed synthetic checkout `850449c49d6996381f740e894b1a81a277977148`. |
| 40156235393 |Two observer and one config cases passed; Python private-directory setup failed before the fixture. |
| 40158041215 |Fixture command failed; the unintended private-workspace artifact was removed without downloading it. Its inner cause remains unavailable. |
| 40159938950 |Extended ACL in runner-temp ancestry refused provisioning before node startup. |
| 40161413799 | 13/14 cases passed; the second child refused at descendant capacity with one original child still counted. |

The bounded diagnostic is default-off and requires explicit disposable-fixture consent. Private scratch uses a fresh fixed `/tmp` root and the unchanged installer ancestry/ACL policy. Uploads contain only explicitly named bounded public reports and command channels.

This completes this finite registry-retirement regression and original local-service fixture repair. Clean-host distribution, six-language/default-library qualification, complete native cost accounting, all lifecycle matrices and production enablement retain their separate requirements in #694 and #736. Their whole acceptance criteria remain open. The successful receipt keeps its executed `95319ec828adbaa096b89cf7063d2ccb9a5164f9` source identity through later documentation and development composition.

Development composition also retains the later TypeScript Buffer-global changes and CI baseline-fetch repair. All 45 executed recipe files, compiled Rust sources, Cargo inputs and selected platform WIT are unchanged. Three shared Python compatibility helpers have later Buffer-selected branches, which the Rust fixture does not select; those new helper bytes and the composed tree were not rebuilt or requalified by the historical run.
