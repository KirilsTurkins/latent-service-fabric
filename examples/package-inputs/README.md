# Small package inputs

The `browser` and `ssr` directories contain explicit v1 recipes and tiny opaque
content fixtures for the [packaging workflow](../../docs/component-development/packaging.md).
They do not execute JavaScript, host a website or start an SSR runtime.

The capsule fixture is generated in memory by
`cargo test -p latent-packaging --locked`, using a real Component Model binary,
nested typed WIT and the checked-in clock contract. No generated Wasm binary or
benchmark archive is retained here.
