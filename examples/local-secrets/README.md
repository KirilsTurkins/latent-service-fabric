# Local secret provider fixture

This is the maintained executable fixture for
[protected local secrets](../../docs/runtime/local-secrets.md). Its WIT imports
`latent:secrets/reader@0.1.0`; the Rust integration test encodes and executes a
small component with that exact surface. It returns a synthetic byte/version
marker or a typed error marker. It does not contain deployment credentials.

On the supported Linux x86_64 host, run:

```sh
cargo test -p latent-wasmtime --test local_secrets --locked
```

The test creates private temporary files and explicit tenant/read grants, loads
a bounded node-owned store, and installs the provider before preparation. It
tests both successful disclosure and rejected access/rotation/cancellation,
including retained resource accounting and actual audit records. Environment
coverage launches a small test child with explicitly synthetic values.

Raw read grants permit the guest to copy plaintext. Operator-only HTTP
credentials use a separate purpose and opaque binding. Neither this fixture nor
declaring its WIT import enables a provider during ordinary standalone startup.
