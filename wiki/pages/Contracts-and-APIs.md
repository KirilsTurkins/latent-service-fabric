<!-- LSF-WIKI-MANAGED -->
# Contracts and APIs

| Authority | Delivered Phase 1 interpretation |
| --- | --- |
| WIT | Component guest contracts; host capabilities are context, logs and clocks. Other packages describe later design. |
| Protobuf | Invoke/Cancel/Status and release/deployment/route/node adapters. Other declarations do not imply live endpoints. |
| JSON Schema | Declarative shapes; runtime codecs enforce supported semantics and bounded inputs. |
| Rust traits | Internal seams, including subsystems awaiting implementations. |
| SDKs | Convenience interfaces preserving semantics; no shipped SDK transport. |

Generic Wasmtime dispatch uses canonical scalar/composite WIT values with lossless integer/float framing. Unsupported resources, futures, streams and async shapes fail explicitly. A declared WIT package is not an installed host implementation.

Domain errors preserve typed guest results. Platform errors retain infrastructure failure and accounting separately. Timeouts or malformed replies do not prove nonexecution or authorize automatic retries. Caller lineage is opaque correlation, not authority.

Implementation versions, content digests, contract versions and minimum fabric requirements are distinct. Publishing 0.1.0-alpha.2 does not renumber WIT or Protobuf contracts.

Authorities: [API map](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/api-surface.md), [WIT codec](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/protocol/wit-values.md), [invocation service](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/protocol/invocation-service.md), [management services](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/reference/management-services.md).
