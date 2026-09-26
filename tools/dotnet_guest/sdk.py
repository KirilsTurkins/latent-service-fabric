"""Instantiate typed facades only for exact imports in authoritative generated C#."""
from pathlib import Path
import re

CAPABILITIES = {
    "http": ("latent:http/client@0.2.0", "IClientImports"),
    "streaming": ("latent:http/streaming@0.3.0", "IStreamingImports"),
    "blob": ("latent:blob/blob@0.2.0", "IBlobImports"),
    "secrets": ("latent:secrets/reader@0.1.0", "IReaderImports"),
    "events": ("latent:events/publisher@0.2.0", "IPublisherImports"),
    "service": ("latent:service/invoke@0.1.0", "IInvokeImports"),
    "random": ("latent:random/random@0.1.0", "IRandomImports"),
    "metrics": ("latent:telemetry/custom@0.1.0", "ICustomImports"),
}


def install(sdk: Path, generated: Path, output: Path) -> dict:
    sources = [path.read_text(encoding="utf-8") for path in sorted(generated.glob("*.cs"))]
    roots = {match[1] for text in sources for match in re.finditer(r"(?m)^namespace ([A-Za-z_][\w]*World)\.wit\.", text)}
    if len(roots) != 1:
        raise ValueError("ambiguous generated C# world namespace")
    root = roots.pop()
    output.mkdir()
    for path in sorted((sdk / "ownership").glob("*.cs")):
        (output / path.name).write_bytes(path.read_bytes())
    (output / "Result.cs").write_text((sdk / "capabilities/Result.cs.in").read_text().replace("@root@", root), encoding="utf-8")
    installed = {}
    for name, (identity, interface) in CAPABILITIES.items():
        namespaces = {match[1] for text in sources if 'DllImportAttribute("' + identity + '"' in text
                      for match in re.finditer(r"(?m)^namespace ([A-Za-z_][\w.]*)\s*[;{]", text)}
        if not namespaces:
            continue
        if len(namespaces) != 1:
            raise ValueError("ambiguous generated C# import identity:" + identity)
        namespace = namespaces.pop()
        if not any("namespace " + namespace + ";" in text and "public interface " + interface + " {" in text for text in sources):
            raise ValueError("generated C# import interface drift:" + identity)
        raw = namespace + "." + interface
        (output / (name + ".cs")).write_text((sdk / "capabilities" / (name + ".cs.in")).read_text()
            .replace("@root@", root).replace("@raw@", raw), encoding="utf-8")
        installed[identity] = raw
    return installed
