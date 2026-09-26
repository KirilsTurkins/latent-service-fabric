"""Check current diagram palettes and inventoried copies; preserve historical bytes."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = "docs/assets/illustrations.json"
COLOR = re.compile(r"#[0-9a-fA-F]{6}\b")
MAX_BYTES = 65536


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for name, value in pairs:
        require(name not in result, f"duplicate JSON key: {name}")
        result[name] = value
    return result


def safe_path(root: Path, relative: str) -> Path:
    require(isinstance(relative, str) and bool(re.fullmatch(r"[A-Za-z0-9_./-]+", relative)), "unsafe illustration path")
    require(not relative.startswith("/") and all(part not in {"", ".", ".."} for part in relative.split("/")), "noncanonical illustration path")
    current = root.resolve(strict=True)
    for segment in PurePosixPath(relative).parts:
        current = current / segment
        require(not current.is_symlink() and not current.is_junction(), "linked illustration path")
        require(current.resolve().is_relative_to(root.resolve()), "illustration escaped repository")
    return current


def read_bytes(root: Path, relative: str) -> bytes:
    source = safe_path(root, relative)
    require(source.is_file() and source.stat().st_size <= MAX_BYTES, f"missing or oversized illustration input: {relative}")
    content = source.read_bytes()
    require(len(content) <= MAX_BYTES, "illustration input grew past bound")
    return content


def read_json(root: Path, relative: str) -> dict:
    return json.loads(read_bytes(root, relative).decode("utf-8"), object_pairs_hook=unique_object)


def git(root: Path, *arguments: str) -> str:
    result = subprocess.run(["git", "-c", "gc.auto=0", *arguments], cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
    require(len(result.stdout) <= 8 * 1024 * 1024, "illustration git inventory exceeds bound")
    return result.stdout.decode("utf-8").strip()


def contrast(foreground: str, background: str) -> float:
    def luminance(color: str) -> float:
        channels = [int(color[offset:offset + 2], 16) / 255 for offset in (1, 3, 5)]
        linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4 for value in channels]
        return sum(value * weight for value, weight in zip(linear, (0.2126, 0.7152, 0.0722), strict=True))
    values = sorted((luminance(foreground), luminance(background)))
    return (values[1] + 0.05) / (values[0] + 0.05)


def render(source: bytes, replacements: dict[str, str], tokens: dict[str, str]) -> bytes:
    text = source.decode("utf-8")
    colors = {value.lower() for value in COLOR.findall(text)}
    require(colors <= replacements.keys(), f"unreviewed source colors: {sorted(colors - replacements.keys())}")
    require(all(token in tokens for token in replacements.values()), "unknown semantic illustration token")
    result = COLOR.sub(lambda match: tokens[replacements[match[0].lower()]], text)
    require(COLOR.sub("COLOR", result) == COLOR.sub("COLOR", text), "non-color illustration bytes changed")
    return result.encode("utf-8")


def prepare(root: Path = ROOT) -> tuple[dict, dict, list[tuple[str, bytes]]]:
    inventory = read_json(root, INVENTORY)
    require(inventory["schema"] == 1 and inventory["mode"] == "dark", "unreviewed illustration contract")
    require(inventory["palette"] == "docs/assets/lsf-palette.json" and inventory["generator"] == "tools/illustration_palette.py", "unreviewed palette owner")
    palette = read_json(root, inventory["palette"])
    schema = read_json(root, "website/content/palette.schema.json")
    roles = set(schema["definitions"]["mode"]["propertyNames"]["enum"])
    require(set(palette) == {"schema", "modes"} and palette["schema"] == 1 and set(palette["modes"]) == {"light", "dark"}, "invalid semantic palette")
    for tokens in palette["modes"].values():
        require(set(tokens) == roles and all(re.fullmatch(r"#[0-9A-F]{6}", value) for value in tokens.values()), "invalid semantic palette roles/colors")
    tokens = palette["modes"][inventory["mode"]]
    for foreground in ("text", "muted", "link"):
        for background in ("canvas", "surface", "raised", "successSurface", "warningSurface"):
            require(contrast(tokens[foreground], tokens[background]) >= 4.5, f"illustration text contrast: {foreground}/{background}")
    for foreground, background in (("successText", "successSurface"), ("warningText", "warningSurface")):
        require(contrast(tokens[foreground], tokens[background]) >= 4.5, "illustration status text contrast")
    for foreground, backgrounds in (("border", ("canvas", "surface", "raised")), ("link", ("canvas", "surface", "raised")), ("successBorder", ("canvas", "successSurface")), ("warningBorder", ("canvas", "warningSurface"))):
        for background in backgrounds:
            require(contrast(tokens[foreground], tokens[background]) >= 3, "illustration boundary/arrow contrast")
    sources = {}
    for entry in inventory["sources"]:
        require(entry["classification"] == "immutable-historical" and entry["reason"] and entry["generator"], "historical exception needs an exact disposition")
        content = read_bytes(root, entry["path"])
        require(hashlib.sha256(content).hexdigest() == entry["sha256"], f"historical bytes changed: {entry['path']}")
        require(entry["path"] not in sources, "duplicate historical SVG")
        sources[entry["path"]] = content
    outputs = []
    for entry in inventory["outputs"]:
        require(entry["classification"] == "maintained-presentation" and entry["source"] in sources, "unreviewed presentation source")
        require(bool(re.fullmatch(r"docs/assets/[a-z0-9-]+-presentation\.svg", entry["path"])), "output is not an explicit presentation copy")
        require(entry["path"] not in sources and entry["path"] not in {name for name, _ in outputs}, "output would replace historical or duplicate SVG")
        require(entry["caption"] and entry["consumers"], "presentation copy requires provenance and consumer")
        for consumer in entry["consumers"]:
            require(Path(entry["path"]).name in read_bytes(root, consumer).decode("utf-8"), f"missing presentation consumer: {consumer}")
        outputs.append((entry["path"], render(sources[entry["source"]], inventory["replacements"], tokens)))
    maintained = set()
    for entry in inventory.get("maintained", []):
        require(entry["classification"] == "maintained-diagram" and entry["owner"], "current diagram needs an owner")
        relative = entry["path"]
        require(bool(re.fullmatch(r"docs/assets/[a-z0-9-]+\.svg", relative)), "invalid current diagram path")
        require(relative not in sources and relative not in maintained
                and relative not in {name for name, _ in outputs}, "duplicate current diagram")
        content = read_bytes(root, relative).decode("utf-8")
        colors = {value.upper() for value in COLOR.findall(content)}
        require(colors and colors <= set(tokens.values()), f"current diagram uses colors outside palette: {relative}")
        require(entry["consumers"], "current diagram needs a consumer")
        for consumer in entry["consumers"]:
            require(Path(relative).name in read_bytes(root, consumer).decode("utf-8"), f"missing current diagram consumer: {consumer}")
        maintained.add(relative)
    tracked = {name for name in git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard").strip("\0").split("\0") if name.lower().endswith(".svg")}
    snapshots = set()
    for entry in inventory.get("snapshots", []):
        require(entry["classification"] == "immutable-snapshot" and entry["reason"]
                and entry["generator"] == "website/scripts/snapshot.mjs", "snapshot SVG needs an explicit owner")
        require(bool(re.fullmatch(r"[a-f0-9]{40}", entry["sourceRevision"])), "snapshot SVG source must be exact")
        require(bool(re.fullmatch(r"website/versioned_assets/version-[0-9][A-Za-z0-9.-]*/docs/assets/[a-z0-9-]+\.svg", entry["path"])), "invalid snapshot SVG path")
        require(entry["path"] not in sources and entry["path"] not in snapshots, "duplicate snapshot SVG")
        require(hashlib.sha256(read_bytes(root, entry["path"])).hexdigest() == entry["sha256"], "snapshot SVG bytes changed")
        snapshots.add(entry["path"])
    expected = set(sources) | {name for name, _ in outputs} | snapshots | maintained
    require(tracked <= expected, f"SVG missing an explicit disposition: {sorted(tracked - expected)}")
    require(set(sources) | snapshots <= tracked, "historical SVG missing from repository inventory")
    return inventory, palette, outputs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="regenerate only named presentation outputs")
    parser.add_argument("--check-legacy", action="store_true", help="verify the recorded Wiki snapshot from local git objects, without fetching")
    arguments = parser.parse_args()
    try:
        inventory, palette, outputs = prepare()
        for relative, content in outputs:
            target = safe_path(ROOT, relative)
            if arguments.write:
                target.write_bytes(content)
            require(read_bytes(ROOT, relative) == content, f"stale presentation output: {relative}; run python tools/illustration_palette.py --write")
        if arguments.check_legacy:
            legacy = inventory["legacyWiki"]
            require(bool(re.fullmatch(r"[a-f0-9]{40}", legacy["revision"])), "legacy snapshot must be exact")
            for entry in legacy["files"]:
                require(git(ROOT, "rev-parse", f"{legacy['revision']}:{entry['path']}") == entry["gitBlob"], "legacy Wiki source identity changed")
        print(json.dumps({"historicalHashes": len(inventory["sources"]), "presentationCopies": len(outputs), "paletteSha256": hashlib.sha256(read_bytes(ROOT, inventory["palette"])).hexdigest(), "mode": inventory["mode"], "legacySnapshotVerified": arguments.check_legacy, "outputs": [{"path": name, "sha256": hashlib.sha256(content).hexdigest()} for name, content in outputs]}, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(f"illustration palette: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
