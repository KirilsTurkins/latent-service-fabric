<!-- LSF-WIKI-MANAGED -->
# Operator CLI

`latent` connects through generated gRPC clients. It does not open server catalogs or execute components locally. Remote commands require `--config FILE`; profiles specify a loopback endpoint, tenant and private token.

| Group | Commands |
| --- | --- |
| Validation | `validate capsule FILE`, `validate deployment FILE` |
| Releases | `release publish`, `release get`, `release list` |
| Deployments | `deployment apply`, `deployment get`, `deployment list`, `deployment delete` |
| Routing | `route get` |
| Execution | `invoke`, `activation get`, `activation cancel` |
| Inventory | `node get`, `node list` for operator credentials |

Each remote command makes one bounded request. There is no automatic retry, pagination, stale-generation replacement or hidden cancel. `--output json` emits a bounded result envelope and preserves unknown outcomes. All groups support `--help`.

Invoke accepts caller activation/lineage IDs, metadata, budgets, priority and deadline. Canonical input is a positional WIT value array such as `["hello"]`, using `application/vnd.latent.wit-values.v1+json`. Later child/outbound/state/blob/effect dimensions are rejected; zero differs from omitted.

A monotonic allowance covers connection and response waiting after preflight. Cold preparation can exhaust it. Ctrl-C stops local waiting and exits 130 without claiming server cancellation. Use another process to explicitly cancel/query a known activation ID. Accepted cancellation does not prove completed native cleanup.

Build, OCI, signing, policy management, durable state and cluster/benchmark commands are outside this CLI. Full limits and semantics: [operator reference](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/reference/operator-cli.md), [quickstart](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/development/standalone-quickstart.md).
