"""Install ergonomic wrappers over exact freshly generated WIT identities.

Only imported current capabilities get a wrapper. Package aliases come from
the generator's actual wasmimport declarations, never guessed version naming.
No WIT resource constructor or raw host handle is exported by the SDK facade.
"""
from __future__ import annotations
from pathlib import Path
import re

CAPABILITIES = {
    "http": ("latent:http/client@0.2.0", set()),
    "streaming": ("latent:http/streaming@0.3.0", {"Upload", "Body", "Chunk", "Response"}),
    "blob": ("latent:blob/blob@0.2.0", {"BlobHandle", "Chunk"}),
    "secrets": ("latent:secrets/reader@0.1.0", {"SecretValue"}),
    "events": ("latent:events/publisher@0.2.0", set()),
    "service": ("latent:service/invoke@0.1.0", set()),
    "random": ("latent:random/random@0.1.0", set()),
    "metrics": ("latent:telemetry/custom@0.1.0", set()),
}


def install(sdk: Path, module: Path) -> None:
    output = module / "lsf"
    output.mkdir()
    (output / "ownership").mkdir()
    (output / "ownership/owner.go").write_bytes((sdk / "ownership/owner.go").read_bytes())
    sources = [(p, p.read_text()) for p in sorted(module.glob("*/wit_bindings.go"))]
    for name, (identity, excluded) in CAPABILITIES.items():
        matches = [(path, text) for path, text in sources
                   if re.search(r"(?m)^//go:wasmimport " + re.escape(identity) + r" ", text)]
        if not matches:
            continue
        if len(matches) != 1:
            raise ValueError("ambiguous-Go-SDK-capability-identity:" + identity)
        source, text = matches[0]
        package = re.search(r"(?m)^package ([a-zA-Z0-9_]+)$", text)
        if package is None or package[1] != source.parent.name:
            raise ValueError("unrecognized-generated-Go-package")
        types = re.findall(r"(?m)^type ([A-Z][A-Za-z0-9_]*) ", text)
        constants = re.findall(r"(?m)^\s+([A-Z][A-Za-z0-9_]*)\s+uint8\s*=\s*\d+\s*$", text)
        aliases = [f"type {item} = raw.{item}" for item in types if item not in excluded]
        aliases += [f"const {item} = raw.{item}" for item in constants]
        directory = output / name
        directory.mkdir()
        raw = package[1]
        (directory / "types.go").write_text(
            f'// Generated aliases from {identity}; no resource constructors.\npackage {name}\n\n'
            f'import raw "wit_component/{raw}"\n\n' + "\n".join(aliases) + "\n", encoding="utf-8")
        (directory / "api.go").write_text(
            (sdk / "capabilities" / (name + ".go.in")).read_text().replace("@raw@", raw), encoding="utf-8")
