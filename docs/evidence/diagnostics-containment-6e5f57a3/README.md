# Typed containment qualification

Four original real-component containment cases passed on source
`6e5f57a3c22f6e08332fd18f6d183b6b6290bc2e`. The test source hash, freshly
built component, original output, tool versions, and hashes of the retained
native binary/source archive are recorded in [receipt.json](receipt.json).

The guest was built on Windows with Rust 1.97.1 for
`wasm32-unknown-unknown`, then componentized and validated with the pinned
`wasm-tools`. The backend was compiled and executed separately on Linux with
Rust 1.97.1, the managed compiler profile, four CPUs, an 8 GiB memory limit,
512 process slots, and the original finite 1800-second watchdog. Its four
cases cover containment cleanup, concurrent deadline expiration, a trap,
and memory pressure. All historical case names, ignore guards, and resource
bounds remain intact; three unselected cases were filtered, not removed.

The repaired assertions preserve the original redacted terminal error and
resource observations while accepting the closed producer-owned execution
diagnostic for deadline and guest memory exhaustion. A plain guest trap
continues to have no inferred exhaustion reason.

The earlier failed GitHub job `110256047724` and failed local source-staging
attempt remain preserved under the task's local `target` reports. Neither is
reclassified as passed. This receipt qualifies the original containment
backend. Full composed Java activation-tree overload, fuel exhaustion, and
delayed-provider observations remain a separate campaign.
