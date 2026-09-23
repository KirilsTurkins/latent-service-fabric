# Standalone Rust capsule qualification

This is developer execution evidence for #544, not the beginner guide or
permission to publish a runtime release. Start with
[Create your own Rust capsule](../component-development/rust-authoring.md).

## Observed execution

[Qualification run 35873297833](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35873297833)
passed on September 23, 2026 for PR head
`23d4ea3c6387d3f122a3517ca172537aa3df6b53`. The source-input receipt digest was
`sha256:a7337ff2d7c8e9f8313f6b6810631857a912aa7a0f066a3a298ffb9cbb451a85`.
Its runtime source inventory covered 2,168 files and 13,541,677 bytes, digest
`sha256:aaab2e6b61f9560542d862d93f1bd177ece1eec4b42e02331717056b07c3e9fb`.
The workflow retains bounded raw logs, build observations, source inventories,
ownership diagnostics, node receipts and the executed tutorial script.

Five independent projects compiled outside the runtime checkout: greeting,
word-count, shipping, HTTP status and recovery. Each used its captured editable
source, vendored maintained SDK, exact Cargo lock, generated WIT contracts and
package inspection. The three tutorials reuse #543's actual implementations.
Each build took 15.98–16.47 seconds in this one CI experiment; these are not
production benchmarks or a compiler performance guarantee.

The signer ran separately after compilation. The real node rejected unsigned
publication, verified the signed packages under exact source-bound builder
approval, and selected their returned publication identities for deployment.
The run made 111 control calls and observed 27 completed activations plus a
deliberately disconnected client. Declared errors, Unicode input, denied HTTP,
trap, fuel exhaustion, memory exhaustion, deadline, explicit cancellation and
client disconnect were followed by successful calls. Recovery returned a fresh
static-state value of 1 after each fault. The HTTP peer observed eight authorized
requests, zero unexpected requests and closure of all three held requests.

Node startup took 46,539,976 ns. Guest peak linear memory for the observed calls
was 1,114,112–1,179,648 bytes. During the two held active-call observations, node
RSS was 81,240,064 and 81,297,408 bytes; these are whole-process, non-atomic
Linux `/proc` samples, not per-guest retained heap measurements. Each active
sample reported one charged activation and 16 MiB of reserved guest memory.
The shared cache contained two entries (270,416 compiled-image bytes), with
five misses and three evictions. Idle checks required zero occupied/quarantined
cells, zero activation quotas and zero activation-scoped owners. At 5, 9 and 17
dormant deployments, no service-resident owner, extra application process,
listener or growing thread population appeared. Deletion and shutdown completed.

## Coverage and reproduction

The same run executed twelve actual wasm-target Rust ownership type-check cases,
including expected borrow/use-after-move errors, and the full admitted guest
capability suite. The latter covers buffered and streaming HTTP, blobs, secrets,
events, local service invocation, randomness and metrics; the existing C blob
cross-check stays enabled. Contract derivation tests cover full-width scalars,
strings, lists, records, results, async kinds and explicit unsupported-shape
rejection. Provenance tests reject mismatched tools, identity, target and builder
approval. No synthetic provider result substitutes for these runtime tests.

All six printed Bash steps in the beginner guide ran unchanged, including valid
and invalid invocation and cleanup. The guide source digest was
`sha256:8a18a0bf849f98d6f8bd9cc375ea21689a648b251c01c67e1fba0fe38da85662`.
Its source-selected complete examples are shared with the tutorial site.

Reproduce with the pinned tools on Linux and a fresh path outside the checkout:

```sh
python3 tools/qualify_rust_capsules.py --output /tmp/my-fresh-rust-qualification
```

`qualification.json` exists only after all stages pass. Failure leaves
`QUALIFICATION-FAILED.json` and stage-specific diagnostics; it does not promote
partial work to success. Earlier runs retained the incorrect fault-classification
assertion and an undersized explicit HTTP policy allowance before their fixes.

The profile is finite, single-node and experimental. It is not a 100k deployment,
throughput, transactional-state or cluster-placement qualification. Build
observations are operator assertions, not authenticated source, hermetic builds
or complete transitive SBOMs. Broad PR CI must also pass before merge. Final PR
and issue comments must link the exact merged source and successful run; this
historical measurement alone does not approve later source. Human newcomer
review remains the separate #345 requirement. Phase 3 and runtime release
publication remain gated on all six language tickets and maintainer approval.
