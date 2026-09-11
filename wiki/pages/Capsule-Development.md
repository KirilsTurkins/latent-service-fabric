<!-- LSF-WIKI-MANAGED -->
# Capsule development

Start with the maintained Rust echo component and WIT contract. `make echo-capsule` produces component bytes, capsule manifest, extracted typed contracts, deployment manifest and canonical input under `target/capsules/echo/`. Generated metadata names the actual digest.

Publish through the local node using the operator CLI. The server validates component identity, tenant, manifest semantics and exported types before durable publication. Apply a deployment and invoke its service/function using canonical WIT values.

Phase 1 permits generic supported scalar/composite arguments and context/log/clock imports. No ambient WASI filesystem, environment, process or network authority is installed. WIT declarations for state, blobs, HTTP, secrets or child calls do not make providers available.

The six SDK directories are interface models, not six end-to-end guest build chains. The maintained executable guest is Rust. OCI push/pull, signing, provenance, SBOM and trusted distributable AOT are Phase 2 work. Local prepared code caching is implemented and does not imply those supply-chain features.

Authorities: [capsule guide](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/component-development/creating-a-capsule.md), [build foundation](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/development/build-foundation.md), [quickstart](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/development/standalone-quickstart.md), [echo example](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/examples/echo-contract/README.md).
