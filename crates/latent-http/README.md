# latent-http

Shared configured buffered/streaming HTTP provider plus a restricted transport for trusted protocol adapters. Exact destinations, address policy, TLS roots, credential references, request/response limits and pool ownership are operator inputs. Guest URLs and headers cannot create ambient network or credential authority.

Immediate requests and committed deferred HTTP effects are different contracts. Only explicitly qualified idempotency/lookup behavior can use the deferred-effect adapter.

## Responsibilities and architecture

| Source | Responsibility |
| --- | --- |
| [src/config.rs](src/config.rs) | Destination/resolution/address/TLS and finite provider limits. |
| [src/provider.rs](src/provider.rs) | Buffered HttpProvider over checked broker calls. |
| [src/execute.rs](src/execute.rs) | Per-hop policy/audit acceptance and immediate operation execution. |
| [src/network.rs](src/network.rs) | Actual pooled socket/HTTP driver ownership; no detached driver. |
| [src/credentials.rs](src/credentials.rs) | Explicit trusted provider credential binding. |
| [src/streaming.rs](src/streaming.rs) | Owned versioned streaming upload/response interface. |
| [src/protocol.rs](src/protocol.rs) | Finite trusted transport for Vault/S3/deferred adapters, not a guest endpoint grant. |
| [src/deferred.rs](src/deferred.rs) | Qualified HTTP effect dispatch/lookup preserving original operation identity. |

## Execution and ownership

1. Install exact destination, resolution, credentials and pool limits; bind a matching broker operation.
2. Accept a bounded activation request under current policy/audit and its original deadline/budget.
3. Resolve/connect/send under finite owned transport resources, repeating acceptance checks for permitted redirects rather than inheriting authority for another endpoint.
4. Retain accepted calls, upload chunks, response buffers and drivers through EOF/abort/cleanup; uncertain remote completion remains explicit.

## Integration boundaries

A guest idempotency header is not qualification for safe retry. The protocol transport cannot grant a guest an HTTP capability. Buffered and streaming host ABI versions have distinct resource/lowering rules, while both keep original accounting. Cancelling a waiter does not prove the remote request did not execute.

## Dependencies and build

Direct workspace dependencies: [latent-core](../latent-core/README.md), [latent-effects](../latent-effects/README.md), [latent-network](../latent-network/README.md), [latent-capabilities](../latent-capabilities/README.md), [latent-policy](../latent-policy/README.md).

Consumers with normal workspace dependency edges include [latentd](../../apps/latentd/README.md), [latent-portable-test-host](../../tools/portable-test-host/README.md). Optional features still gate the selected graph; target-specific and test edges are also declared in the manifests.

Use [Cargo.toml](Cargo.toml) for external dependencies, target gates and test/build edges; [the workspace manifest](../../Cargo.toml) and [the toolchain guide](../../docs/development/toolchain.md) own current pins. Dependency presence does not install a runtime service.

## Tests and verification

The [package entry point](src/lib.rs) and the module links above are the source map. [The workspace package guide](../../docs/development/workspace-packages.md) explains feature/target selection, generated inputs and the registered test workflow.

Inspect a registered suite from the repository root without building or running it:

```sh
python3 tools/test.py explain --suite latent-http.lib.latent-http
```

Use `list --output json` to find the remaining package targets. Follow the suite's recipe, platform and prerequisites for preparation, discovery and execution; a registration or compile-only check is not a passing execution/qualification result.

Representative source tests (not a complete coverage inventory):

- [`actual_protocol_dispatch_policy_can_refuse_post_after_qualification_without_remote_mutation`](src/deferred/tests/authorization.rs)
- [`two_kib_encoded_reply_keeps_the_complete_physical_provider_reservation`](src/deferred/tests/campaign.rs)
- [`declared_rejection_and_positive_abort_commit_no_http_intent_or_mutation`](src/deferred/tests/campaign.rs)
- [`provider_cancellation_during_tls_or_reply_retires_actual_socket_before_refund`](src/deferred/tests/campaign.rs)

## Related documentation

- [Policy-scoped outbound HTTP](../../docs/runtime/outbound-http.md)
- [Bounded streaming HTTP](../../docs/runtime/streaming-http.md)
- [Shared provider pools](../../docs/runtime/provider-pools.md)
- [Qualified deferred HTTP delivery](../../docs/development/deferred-http.md)
- [Signed deferred HTTP installation](../../docs/development/deferred-http-installation.md)
- [Qualified HTTP effects](../../docs/reference/qualified-http-effects.md)
- [Workspace package index](../README.md)
- [Architecture index](../../ARCHITECTURE.md)
