# Workspace package index

The root [Cargo workspace](../Cargo.toml) contains **53 Rust packages**: 42 libraries under `crates/`, three applications, two Rust SDK packages and six tool packages. Every member has a package README linked below. This index covers workspace members; independently built application examples and language-runtime projects retain their own guides.

Use [the package architecture walkthrough](../docs/development/workspace-packages.md) for end-to-end flows, ownership boundaries and test selection. Package READMEs map concrete modules, implementation status, lifetimes, dependency/feature gates, source tests and related specifications. The manifest and implementation remain the authority for exact signatures and limits.

## Status and navigation

An interface trait is not an installed service. In particular, workflows, remote invocation and the clustered control binary remain scaffolds; identity/trigger traits have concrete adapters elsewhere. Optional research backends are not workspace runtime implementations. Development transaction code has separate remaining qualification gates and is outside the published alpha.5 toolkit.

## Foundations and generated contracts

| Package | Responsibility |
| --- | --- |
| [`latent-core`](latent-core/README.md) | Shared identity, error, lifecycle, time and resource-ownership vocabulary for the workspace. |
| [`latent-manifest`](latent-manifest/README.md) | Typed capsule, deployment, binding and trigger documents, bounded JSON codecs and semantic validation. |
| [`latent-contracts`](latent-contracts/README.md) | Structural contract descriptors and bounded compatibility/binding analysis. |
| [`latent-component-bindings`](latent-component-bindings/README.md) | Single build-generated Rust binding owner for LSF's authoritative WIT worlds. |
| [`latent-component-threading`](latent-component-threading/README.md) | Bounded post-link transforms and complete component-routing authentication for the explicit Rust continuation source profile; engine thread creation remains disabled. |
| [`latent-rpc`](latent-rpc/README.md) | Build-generated Protobuf messages, Tonic clients/servers and descriptor-set ownership, plus checked platform-error and transaction conversions. |

## Packages, trust and publication

| Package | Responsibility |
| --- | --- |
| [`latent-artifacts`](latent-artifacts/README.md) | Package/content identities, a bounded directory artifact repository, publication lifecycle and reusable raw/preparation inputs. |
| [`latent-packaging`](latent-packaging/README.md) | Deterministic assembly and inspection of exact supplied package inputs. |
| [`latent-oci`](latent-oci/README.md) | Bounded OCI distribution of exact package bytes and detached signature/provenance evidence. |
| [`latent-signing`](latent-signing/README.md) | Local package signing, strict Ed25519/DSSE evidence and bounded publisher/builder trust verification. |
| [`latent-policy`](latent-policy/README.md) | Two concrete authority owners: bounded tenant capability policy and supply-chain package admission. |

## Local execution and ownership

| Package | Responsibility |
| --- | --- |
| [`latent-routing`](latent-routing/README.md) | Immutable local routing and revision-policy contracts. |
| [`latent-activation`](latent-activation/README.md) | Invocation requests, validated envelopes, typed outcomes and lifecycle/journal ports. |
| [`latent-admission`](latent-admission/README.md) | Concrete local resource admission before scheduling and execution. |
| [`latent-scheduler`](latent-scheduler/README.md) | Bounded fair local scheduling over fixed-capacity generic execution-cell pools. |
| [`latent-executor`](latent-executor/README.md) | Engine-independent preparation, execution and cleanup contracts. |
| [`latent-wasmtime`](latent-wasmtime/README.md) | Concrete Component Model execution backend with fresh activation Stores, exact host ABI validation, bounded prepared-code reuse and optional authenticated local AOT reuse. |
| [`latent-node`](latent-node/README.md) | Local activation lifecycle orchestration and activation-scoped transaction integration. |

## Capability and protocol boundaries

| Package | Responsibility |
| --- | --- |
| [`latent-capabilities`](latent-capabilities/README.md) | Concrete activation capability broker and namespace authority integration. |
| [`latent-network`](latent-network/README.md) | Shared address classification and explicit bounded DNS resolution for network providers. |
| [`latent-protected-files`](latent-protected-files/README.md) | Protected host file and directory primitives used by secrets, credentials and durable state roots. |
| [`latent-secrets`](latent-secrets/README.md) | Linux operator-owned local secret generations and explicitly granted guest disclosure. |
| [`latent-vault`](latent-vault/README.md) | Linux x86-64 Vault KV-v2 secret provider using explicit references and bounded shared plaintext ownership. |
| [`latent-http`](latent-http/README.md) | Shared configured buffered/streaming HTTP provider plus a restricted transport for trusted protocol adapters. |
| [`latent-streams`](latent-streams/README.md) | Bounded outbound TCP/TLS stream implementation for explicit qualification. |
| [`latent-nats`](latent-nats/README.md) | Shared bounded TLS JetStream publication, explicit pull triggers and a qualified deferred event adapter. |
| [`latent-blobs`](latent-blobs/README.md) | Immutable large-value storage with staged writers, ranged readers and explicit transfer ownership. |
| [`latent-ingress`](latent-ingress/README.md) | Protocol adaptation and concrete bounded buffered HTTP application values. |
| [`latent-wire`](latent-wire/README.md) | Concrete bounded standalone RPC adapters plus general channel/frame interfaces. |

## State and deferred effects

| Package | Responsibility |
| --- | --- |
| [`latent-state`](latent-state/README.md) | Concrete protected transactional storage foundation. |
| [`latent-commit`](latent-commit/README.md) | Host-owned atomic command completion across state, durable result, outbox and inbox. |
| [`latent-effects`](latent-effects/README.md) | Durable deferred-effect identity, authority, transition and dispatch machinery. |

## Control and observation

| Package | Responsibility |
| --- | --- |
| [`latent-control-store`](latent-control-store/README.md) | Embedded deployment/control catalog with immutable route publication. |
| [`latent-rollout`](latent-rollout/README.md) | Bounded node control coordinator for durable manual rollout operations, canary review and rollback. |
| [`latent-telemetry`](latent-telemetry/README.md) | Bounded logs, traces, metrics and activation observations on one node-owned exporter. |
| [`latent-audit`](latent-audit/README.md) | Immutable administrative/security audit facts with a concrete bounded local durable journal. |

## Interface scaffolds and future integration

| Package | Responsibility |
| --- | --- |
| [`latent-identity`](latent-identity/README.md) | Authentication, authorization, delegation and node/workload identity interfaces. |
| [`latent-triggers`](latent-triggers/README.md) | Common trigger event, cursor, registry, source and dispatch interfaces. |
| [`latent-workflows`](latent-workflows/README.md) | Durable workflow continuation and suspension vocabulary. |
| [`latent-wrpc`](latent-wrpc/README.md) | Remote-invocation transport contracts for a future node-to-node data plane. |

## Test foundations

| Package | Responsibility |
| --- | --- |
| [`latent-test-process`](latent-test-process/README.md) | Neutral owned child-process and resource-observation helpers for tests. |
| [`latent-testkit`](latent-testkit/README.md) | Explicit deterministic and conformance helpers for tests, with an optional node/runtime harness. |

## Applications

| Package | Responsibility |
| --- | --- |
| [`latentd`](../apps/latentd/README.md) | Standalone node composition root and product command entry point. |
| [`latent`](../apps/latent/README.md) | Standalone operator CLI. |
| [`latent-control`](../apps/latent-control/README.md) | Reserved clustered control-plane binary package. |

## Rust SDKs

| Package | Responsibility |
| --- | --- |
| [`latent-sdk`](../sdk/rust/README.md) | External Rust client SDK for standalone invocation, management and additive transaction/dispatcher operations. |
| [`latent-guest`](../sdk/rust-guest/README.md) | Typed Rust capability and ownership helpers inside a WebAssembly component. |

## Build, test and measurement tools

| Package | Responsibility |
| --- | --- |
| [`latent-toolchain-smoke`](../tools/toolchain-smoke/README.md) | Compile probes and maintained component fixtures for the pinned build foundation. |
| [`latent-optimization-workloads`](../tools/optimization-workloads/README.md) | Identical deterministic workload logic for the native comparison reference and Wasm benchmark component. |
| [`latent-optimization-bench`](../tools/optimization-bench/README.md) | Explicit measurement tooling: an external load client, native reference, container supervisor and artifact identity probe. |
| [`latent-renderer-profile`](../tools/renderer-profile/README.md) | Finite operator-controlled Wasmtime qualification host for the closed Angular renderer fixture. |
| [`latent-angular-renderer-adapter`](../tools/angular-renderer-adapter/README.md) | Fixed wasm32 guest adapter between the private synchronous closed JavaScript renderer and the public asynchronous `latent:web/application@0.1.0` contract. |
| [`latent-portable-test-host`](../tools/portable-test-host/README.md) | Controlled portable component test executable using the production Wasmtime backend and value codec without instantiating a production node. |

## Isolated package projects

Two additional tracked Rust packages declare independent workspaces and locks.
They are outside the root's 52-member build/test selection; their READMEs explain
the consuming qualification or source investigation.

| Package | Responsibility |
| --- | --- |
| [latent-native-vm-fixture](../tools/native-fixture/README.md) | Explicit synthetic public test trust/package generator for the authenticated native VM runner. |
| [latent-rust-std-stack-source-transform](../sdk/rust-standard-runtime/stack-transform/README.md) | Source-only post-link shadow-stack/owned-entry experiment, not selected by the maintained guest builder. |

## Working on a package

- [Contribution workflow](../CONTRIBUTING.md) and [selected toolchains](../docs/development/toolchain.md).
- [Registered preparation, discovery and test execution](../docs/development/local-tests.md).
- [Generated WIT/Protobuf ownership and dependency direction](../docs/development/build-foundation.md).
- [Architecture decisions and implementation guides](../ARCHITECTURE.md).
