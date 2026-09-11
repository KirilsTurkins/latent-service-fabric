<!-- LSF-WIKI-MANAGED -->
# Development workflow

Develop from `development`, use focused feature/fix/chore branches and target PRs to development. Review required CI on the final commit. `release` carries published alpha source; tags identify exact versions. The isolated `docs/wiki` branch must never merge into development or release.

Read acceptance criteria and ADRs. WIT, Protobuf and schemas define contracts; code/SDKs preserve them. Architectural changes use ADR/RFC review. Research remains unpromoted until explicitly accepted.

Install pinned tools and select [validation tiers](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/VALIDATION.md). Ordinary checks require no fresh 100k or long-soak campaign. Change-specific checks should exercise scope, ownership and failure behavior. Keep raw archives and build outputs out of incidental documentation changes.

Update canonical docs with behavior changes. Wiki pages link those authorities and distinguish current/future features. All Wiki assets and publication remain on the dedicated branch, separate from a code release.

Authorities: [contributing](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/CONTRIBUTING.md), [toolchain](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/development/toolchain.md), [retention](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/testing/benchmark-retention.md).
