"""Maintained standalone provider identities required by language runtimes."""

RUNTIME = {
    "clockMonotonic": ("latent:clock/monotonic@0.1.0", "activation-monotonic-v1", "now-nanos", "clock"),
    "clockWall": ("latent:clock/wall@0.1.0", "activation-wall-v1", "now-unix-millis", "clock"),
    "random": ("latent:random/random@0.1.0", "system-random-v1", "u64-value", "random"),
}


def profiles(language):
    if language not in {"go", "dotnet", "java", "c"}:
        raise ValueError("runtime-grant-language")
    if language == "c":
        return {**RUNTIME, "random": (*RUNTIME["random"][:2], "bytes", "random")}
    if language == "java":
        return {name: value for name, value in RUNTIME.items() if name != "random"}
    return RUNTIME if language == "go" else {"clockMonotonic": RUNTIME["clockMonotonic"]}
