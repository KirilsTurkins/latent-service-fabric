"""Install separate ergonomic helpers for exact canonical Java WIT imports."""
from pathlib import Path


def install(sdk: Path, bindings: Path, output: Path) -> list[str]:
    source = (bindings / "Bindings.java").read_text(encoding="utf-8")
    bridge = (bindings / "probe.c").read_text(encoding="utf-8")
    installed = []
    for identity, name, owner in (("latent:state/key-value@0.2.0", "State", "LatentStateKeyValueTransaction"),
                                  ("latent:intents/staging@0.1.0", "Intent", "LatentIntentsStagingIntent")):
        if f'__import_module__("{identity}")' not in bridge:
            continue
        marker = ("public static final class " + owner + " extends Resource") if name == "State" else ("public record " + owner + "(")
        if source.count(marker) != 1:
            raise ValueError("canonical Java transaction facade type drift:" + identity)
        if name == "Intent" and "State" not in installed:
            raise ValueError("intent staging requires the canonical imported state owner")
        target = output / "dev/latent/guest" / (name + ".java")
        if target.exists():
            raise ValueError("application overrides Java transaction SDK source")
        target.write_bytes((sdk / "runtime/dev/latent/guest" / (name + ".java.in")).read_bytes())
        installed.append(name)
    return installed
