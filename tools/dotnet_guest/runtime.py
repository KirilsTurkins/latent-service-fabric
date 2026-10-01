"""Select finite NativeAOT support from declared authority and emitted imports."""
from __future__ import annotations

CLOCK = "latent:clock/monotonic@0.1.0"
ACTIVATION = "latent:runtime/activation@0.1.0"
HTTP = "latent:http/streaming@0.3.0"
ADAPTERS = {
    "closed": ("dotnet-closed-runtime", "runtime.wasm"),
    "runtime": ("dotnet-activation-runtime", "activation-runtime.wasm"),
    "http": ("dotnet-http-runtime", "http-runtime.wasm"),
}
EXAMPLES = tuple("tools/toolchain-smoke/examples/" + example.replace("-", "_") + ".rs"
                 for example, _binary in ADAPTERS.values())
WASI_HTTP_IMPORTS = frozenset({
    "wasi:http/types@0.2.0", "wasi:http/outgoing-handler@0.2.0"})
WASI_IMPORTS = frozenset(
    "wasi:" + name + "@0.2.6" for name in (
        "cli/environment", "cli/exit", "cli/stdin", "cli/stdout", "cli/stderr",
        "cli/terminal-input", "cli/terminal-output", "cli/terminal-stdin",
        "cli/terminal-stdout", "cli/terminal-stderr", "clocks/monotonic-clock",
        "clocks/wall-clock", "io/error", "io/poll", "io/streams",
        "filesystem/preopens", "filesystem/types", "random/random")) | WASI_HTTP_IMPORTS


def select(declared: list[str], emitted: list[str]) -> str:
    """An emitted WASI dependency is never a grant of LSF network authority.

    The caller extracts these identities from bounded authoritative wasm-tools
    graphs. Exact resource and operation shapes are then checked by actual
    component composition and the normal frozen host-ABI admission checks.
    """
    declarations, actual = set(declared), set(emitted)
    if len(declarations) != len(declared) or len(actual) != len(emitted):
        raise ValueError("dotnet-runtime-duplicate-import")
    if CLOCK not in declarations:
        raise ValueError("dotnet-runtime-requires-declared-monotonic-clock")
    if any(name.startswith("wasi:") for name in declarations):
        raise ValueError("dotnet-runtime-source-cannot-declare-ambient-wasi")
    for name in sorted(actual):
        if name.startswith("wasi:"):
            if name not in WASI_IMPORTS:
                raise ValueError("dotnet-runtime-unsupported-wasi-import:" + name)
        elif name not in declarations:
            raise ValueError("dotnet-runtime-undeclared-emitted-import:" + name)
    for name in sorted(declarations):
        if name.startswith("latent:runtime/activation@") and name != ACTIVATION:
            raise ValueError("dotnet-runtime-unsupported-activation-version:" + name)
        if name.startswith("latent:http/streaming@") and name != HTTP:
            raise ValueError("dotnet-runtime-unsupported-http-version:" + name)
    # Generated SDK calls already import typed HTTP directly and do not require
    # the default BCL adapter or its activation-owned pending-call machinery.
    # Select that adapter only for its declared authority AND the actual emitted
    # outgoing WASI HTTP graph. Declarations alone are not evidence of BCL use.
    if HTTP in declarations and ACTIVATION in declarations and WASI_HTTP_IMPORTS <= actual:
        return "http"
    return "runtime" if ACTIVATION in declarations else "closed"
