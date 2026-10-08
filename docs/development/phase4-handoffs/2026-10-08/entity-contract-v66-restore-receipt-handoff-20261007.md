# Exact staged-restore receipt recovery

Candidate: `f4ab131b3ec60b5206b50f4dd00fff83f05410bc` (tree `5898833951da18099c77cb25aa493a53731e6544`). The implementation commit is `cdc88f5b2fd8a74ea3c8e58bf1b38b54bf7cf498`, based on the reviewed #808 current-development merge `27aaac77308aaa656d54280ac4f341494e4509f7`. The second commit repairs only the inherited historical CI expectation for the already reviewed identity-full lane. Current #808 has independently received qualified HTTP repairs; integrate these two bounded deltas after Native qualification rather than replacing its branch.

Owned clean tree: `C:\Users\turkins\Desktop\lf-p4-restore-receipt-v65`. Normal-published checkpoint branch: `fix/phase4-restore-receipt-source-contract-v66`. No extra PR was opened.

## Changed behavior

`ProtectedStoreOwner::recover_restore_receipt` returns the original completed operation's receipt through the same fixed physical worker and original snapshot custody. It performs no import, control mutation, checkpoint write, adoption or resume. It rechecks same-file input/reservation, pointer identity of installed owners, original operation/operator/runtime/window, actual snapshot bytes and artifacts, current source window, actual imported rows and destination identity, completed reconciliation guard, current protected clock/dispatch checkpoint and consumed final original read fence. `RestoreStageOwners::verify_completed` is a mandatory completed-view review, with no approved default.

The private completion description is retained only by the same prepaid file custody. Incomplete/uncertain stages, different owners or requests, adoption already prepared, corruption, revocation and expired original lifetime refuse. Normal `stage_restore`'s attempted-stage refusal is unchanged. Process restart or retired custody still requires the separately owned explicit restored-root workflow; this feature provides no new-boot permission or universal replay claim.

## Actual Source evidence

Fresh Linux Source campaign `entity-restore-receipt-source-linux-20261007-v2` passed all seven original gates at the exact candidate, including 204 Python cases with no skips/errors, coverage 88 baseline / 270 current / 143 delegated owners, contract generation, foundation, repository/docs checks, pinned fmt, full resolved locked offline all-features Cargo metadata and authenticated Go formatter / all 13 SDK generated-file checks. Elapsed 125.8 seconds. Source stayed clean and unchanged; every original process was reaped and every log byte count/SHA was verified.

Receipt SHA-256: `2833b43d018e374660d19b45e327b16d5e209582f259d8638019149021a3d14d`. The earlier `cdc88` campaign's exact single historical-expectation failure and all six passing gates remain preserved in `entity-restore-receipt-source-linux-20261007-v1`.

## Actual Native evidence and publication

Portable executed the exact six-step recipe on frozen `f4ab` in `portable-v2-state399-retained-receipts-native-20261007-v112`. All six steps passed: six focused actual restore schedules, State 328 with no ignores, protected-files 25 with one unchanged controlled ignore, Core native-capacity 11, affected all-target checks and ordinary Clippy. The actual compiled State listing exactly matches all 328 registered names. Source stayed clean and unchanged; all processes were reaped with no infrastructure failure, in 94.03 seconds. Native receipt SHA-256: `11e7738c06de4d4b9c554bfca8d424bb5ce97ce64ffe899b3b3a2536ddb4a41d`.

The implementation was integrated into existing #808 on `8d7912f5`, preserving its qualified HTTP repairs and the historical CI expectation fix. Combined head `e9014ee1155f89bbe323f858fe02b87a55a8d11f` passed fresh seven-gate Linux Source validation and was normally pushed after exact previous-head/ancestor/clean guards. GitHub verified the new head and mergeability. Its Source receipt SHA-256 is `e25897d34258a2025a8806409ffd91bad3ae44b537131c04d5fc4e7dad0b82f3`.

`entity-contract-v68-recovery808-native-source-closure.json` compares every byte of all 237 State/Core/protected-files/test-process package files, whole workspace manifest/lock/toolchain/config and affected catalogue rows: they are identical to Native-tested `f4ab`. This permits the narrow proof's reuse while retaining its original attribution. It establishes no full-CI or complete issue acceptance claim.

## Preserved Native recipe

Use the original bounded controller and `entity-contract-v65-restore-receipt-native-steps-20261007-v1.json`, SHA-256 `b0a643f80cf9af36a4ae081e98c06198144ae3df54769d783bcbc997ba2d29a4`. Six commands check affected all-target/all-feature code, execute the six actual protected-root schedules, run full State/protected-files libraries, preserve original Core native-capacity cases, run registered ordinary Clippy and list the exact State harness. The reviewed catalogue changes only State 322 to 328 and adds the six names; all other suites, cases, ignores, floors, platforms, resources, recipes, prerequisites and deadlines are unchanged. Actual compilation/listing/execution must establish those names and counts.

The six schedules cover lost-response recovery with unchanged real checkpoint/import counters and retained original capacity; changed operation/operator/window; every current owner revoked; failed partial sealing; actual protected-checkpoint corruption; and same installed owner plus mandatory final read-fence consumption. Fixture callbacks are controlled inputs, not authenticated management or production-policy evidence.

The separate reader-retirement child `6a7bfa58acf4e396fbc4dde372b471bb4ea8cd53` adds only a cfg(test) pause and one real abandoned-reader/drain schedule, registering State 329. It is normally published on `test/phase4-restore-reader-retirement-v67`, has seven-gate Source proof `entity-restore-reader-source-linux-20261007-v1` (receipt SHA-256 `d14507b09f8101f072db3d015f3799b52776147851b1cd7140e24fea0706c9e6`), and remains Native-pending. This extra case is not included in #808 `e901` or attributed to the earlier six-case Native proof.

## Remaining acceptance

#398/#399 remain open. This slice does not qualify ordinary authenticated management/CLI, true quiescence of all installed command/query/commit/dispatch/ACK/maintenance owners, a restored new boot, complete signed workload/payload/format inventory, actual external-effect success followed by pending-history restore, or approved reconciliation and resume. The existing configured StateRuntime/CommandAdmissionFactory and Phase's active Effects/recovery bindings must be reused for those operations; no second runtime/service or caller-supplied permission flag is introduced here.
