# Java transaction integration handoff — 8 October 2026

PR #802 targets `development` and remains a draft for #718. The integration combines development's native ownership guarantees with the current command/query admission and affine completion hooks. `latent-node` and `latentd` share the original admission owner. Already-owned completion retains the original deadline, cancellation and native capacity after accounting freezes; cleanup is idempotent only after positive physical retirement.

The source integration at `8aed1390191187efc6948ae74e94f313fc650a5c` passed all 133 Linux node library tests with exact discovery, including the 13 protected-store ownership oracles. Control-store discovery matched 253 cases: 252 passed and the original ignored test remained ignored. The Linux source/compiler/CI fixture batch passed 141 tests. Nine composition source associations were reviewed and refreshed without changing finite support rows or limits.

Dependency integration at `85baee21ebbfd5d6b2dc05671959f0e24b618146` passed 136 focused Linux checks with seven preserved platform skips. It incorporates Wasmtime 48.0.5, hyper-util 0.1.21, renderer jco 1.35.0, client Node types 26.6.3 and cache restore 6.1.0. The Phase 4 WIT ABI digest remains unchanged. Completed renderer follow-up `3a49274dcd381c0d79a85ba58db5b611365c9376` adds the explicit preview2-shim compatibility dependency and accurate componentization declarations.

Implementation and local tests stopped at this cleanup handoff. Current-head hosted CI and actual signed Java guest, HTTP recovery, crash/retention and value/child qualification remain required. No new signing or qualification clock was started. These source and native-host checks do not establish completion of #718 or the feedback tracker.
