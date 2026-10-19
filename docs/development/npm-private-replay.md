# Private npm qualification replay

The default-false `private_npm_replay` input in TypeScript guest qualification runs a fresh
private registry capture, four offline component builds, fresh demo signing and the normal
signed lifecycle. Normal pull-request and development jobs retain their commands and limits.

The replay consumes only the fixed b53969d95763c60b29a5b14a06879689dbdb061e qualification
(run 39290090984, job 118188191208). It requires completed normal and captured-library
qualification steps, exact unchanged runtime/SDK/compiler source inputs, both original source
inventories, the real normal node receipt with at least 27 invocations, all five native product
identities and four component package inventories. Changed production inputs refuse before
native products are acquired. The diagnostic does not fabricate a new normal qualification.

Only the single source-bound Actions artifact is eligible. Bounded range reads retain each
selected regular member's digest and the original artifact identity; unselected archive members
are not downloaded. The Actions token is scoped to the retrieval step and never reaches the
compiler. Current fixture source and original compiled source are recorded separately.

The compiler installation and all private packages are acquired afresh. The private campaign
retains its original strict TLS, authentication, integrity, exact-review and component equality
requirements. Its public receipt must pass before it supplies qualification evidence. This
replay does not claim a clean host, hermetic execution, production publishing or full issue #685
completion. An unrelated native runtime change requires a new matching normal qualification.
