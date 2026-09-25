# Latent Service Fabric

Latent Service Fabric (LSF) runs stateless service capsules on a standalone Linux
node. A capsule is a WebAssembly component with typed interfaces and declared
capabilities. Deploying another service adds code and bounded metadata; it does
not create an idle service process, thread, socket, guest heap or connection pool.

An incoming request creates an **activation** in a fixed pool of execution cells.
Each activation gets fresh guest state. The node reclaims its resources when the
request finishes, fails, times out or is cancelled.

## Try LSF

Follow [Run your first node](docs/start/first-node.md) to build LSF, start a local
node, deploy a capsule, invoke it and try it again after a restart. The walkthrough
includes the commands and expected results. Then
[create a capsule](docs/component-development/creating-a-capsule.md) or
[call it from your application](docs/learn/use-a-client.mdx).

With an independently approved developer candidate, follow
[application development with packaged tools](docs/start/application-development.md)
for Windows/WSL2, direct Linux, explicit SSH and native Windows capsule tests.
This path keeps application source outside the LSF checkout and uses selected
prebuilt runtime and compiler distributions.

LSF is in alpha. Native binary publication is on hold; use the source walkthrough
until an approved release is available. The historical `0.1.0-alpha.3` release is
source-only. See [installation](docs/installation.md) for availability and host
requirements. Maintainers track remaining work and approval in the
[release gate review](docs/phase-3-gate-review.md).

The [documentation website](https://kirilsturkins.github.io/latent-service-fabric/)
provides Start, Learn, How-to, Reference, Understand and Contribute sections.
Choose the development documentation for this branch; published versioned guides
describe their own release and may differ from the current source.

## What you can build

| Goal | Current support | Start here |
| --- | --- | --- |
| Run a stateless service | Typed Component Model contracts, bounded execution and fresh state per activation | [Create a capsule](docs/component-development/creating-a-capsule.md) |
| Call a service from an application | Native Rust, C, TypeScript, Go, Java and C# clients using the shared local RPC profile | [Client guide](docs/learn/use-a-client.mdx) |
| Use host capabilities | Policy-controlled providers with shared pools and activation-owned resources | [Use capabilities](docs/learn/use-capabilities.md) |
| Serve a website | Static assets through the shared HTTP listener, without a guest activation for static responses | [Static sites](docs/component-development/static-sites.md) |
| Render an Angular application | A supported, bounded server-rendering profile with browser assets | [Angular walkthrough](docs/learn/build-and-deliver-angular.mdx) |
| Deliver and recover changes | Signed packages, OCI transfer, admission, managed deployment, staged rollout, canary observation and rollback | [Delivery guide](docs/phase-2-delivery.md) |

External client support and **capsule authoring** are separate: all six client
languages can call LSF, and each has a dedicated guest authoring path with
documented supported profiles and limitations. The
[guest SDK guide](docs/component-development/guest-sdk.md) describes the available
build paths without implying that every external client is also a guest SDK.

Standalone node configuration exposes outbound HTTP, local blobs, activation
clocks and OS-backed randomness through explicit provider installations.
Other maintained provider integrations use trusted Rust embedding; consult the
[provider reference](docs/reference/standalone-providers.md) before choosing a
setup. Durable application state, transactional effects and clustering remain
planned work. Management RPCs are local; application HTTP ingress has its own
[listener and security configuration](docs/reference/http-ingress.md).

[![Build a package, sign and admit it, then invoke a capsule or serve a website through the node.](docs/assets/package-delivery.svg)](docs/assets/package-delivery.svg)

## Resource and security model

```text
resident state = fixed node runtime + bounded catalog metadata + active activations + bounded shared caches
```

The number of node processes, threads, sockets and execution cells must not grow
with the number of deployed services. Runtime limits bound queues, budgets,
provider resources and retained results. Cleanup uncertainty keeps a cell
quarantined and accounted for instead of making it available for reuse.

A signature, a package checksum and an invocation ID have different purposes.
Package verification establishes provenance; current policy and admission decide
whether execution is allowed. Capabilities require explicit grants. The current
in-process runtime is not a separate-process security boundary against an engine
compromise. Read [architecture](ARCHITECTURE.md),
[execution security profiles](docs/runtime/execution-security-profiles.md) and
[security reporting](SECURITY.md) for the supported boundary.

## Repository map

| Path | Contents |
| --- | --- |
| `apps/` | `latentd` standalone node, `latent` operator CLI and the clustered control-plane placeholder |
| `crates/` | Runtime, storage, policy, provider and management implementations |
| `wit/` | Typed capsule interfaces and platform capability contracts |
| `api/proto/` | Invocation, node and management RPC definitions |
| `schemas/` | Declarative resource JSON Schemas |
| `sdk/` | External clients, common profile and guest bindings |
| `examples/` | Capsule, application, contract and deployment examples |
| `docs/` | Guides, references, architecture and engineering records |
| `adr/`, `rfcs/`, `research/` | Accepted decisions, future proposals and experimental work |
| `tests/`, `benchmarks/` | Test specifications and retained measurements; executable tests also live with their implementations |
| `tools/`, `website/` | Build and validation tools and the documentation site |

WIT defines guest interfaces, Protobuf defines RPCs, and JSON Schema defines
declarative documents. SDKs and generated bindings consume those authorities;
they do not define independent wire contracts.

## Contribute and validate

Start with [CONTRIBUTING.md](CONTRIBUTING.md) for the change workflow and
[toolchain setup](docs/development/toolchain.md) for exact supported versions.
After installing those prerequisites, the normal Linux validation entry point is:

```bash
python3.13 -m venv .venv
. .venv/bin/activate
python -m pip install --requirement tools/requirements.lock
make validate
```

For a focused change, use the [local test runner](docs/development/local-tests.md)
to select the relevant registered suite. CI uses reviewed
[change profiles](docs/development/ci-profiles.md); generated files stay in build
output directories. Expensive scale probes and resource campaigns require
explicit selection. [VALIDATION.md](VALIDATION.md) explains coverage and limits.

[Engineering records](docs/development/engineering-records.md) retain past gate
decisions and measured comparisons with their original source and environment.
They are evidence for those runs, not current installation instructions or a
claim of production cluster capacity.

## License

Apache License 2.0. See [LICENSE](LICENSE).
