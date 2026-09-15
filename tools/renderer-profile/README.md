# Renderer qualification host

An operator-controlled finite Wasmtime probe for the
[Angular renderer qualification](../../examples/renderer-profile/README.md).
It is not part of `latentd`, admission, the native loader or an application API.
It compiles the supplied fixture once, exercises fresh bounded Stores and
failure cleanup, writes one hydration fixture and emits one compact JSON report.
The compilation caller must provide an outer process/resource boundary.
