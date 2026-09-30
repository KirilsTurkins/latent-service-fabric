"""Captured authoring inputs for the explicit Phase 4 guest template."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = "transactional-aggregate"
INPUT_FORMAT = "lsf-wit-values-v1"
RESULT_FORMAT = "lsf-wit-values-v1"


def augment(files: dict[str, bytes], project: dict) -> None:
    """Declare exact compatibility; only authenticated node admission grants it."""
    for package in ("state", "intents"):
        files["wit/deps/" + package + "/package.wit"] = (ROOT / "wit/platform" / package / "package.wit").read_bytes()
    profile = (ROOT / "sdk/profile/transaction-requirements-v1.json").read_bytes()
    schema = (ROOT / "examples/rust-capsules" / TEMPLATE / "state-schema.json").read_bytes()
    files["transaction-profile.json"] = profile
    files["state-schema.json"] = schema
    declaration = {
        "apiVersion": "latent.dev/v1", "kind": "TransactionBinding",
        "capsule": project["service"], "deployment": project["name"], "binding": project["name"],
        "profile": "lsf-transaction-v1", "hostAbiDigest": json.loads(profile)["hostAbiDigest"],
        "namespace": TEMPLATE, "stateSchema": "sha256:" + hashlib.sha256(schema).hexdigest(),
        "operations": [{"operation": name, "mode": mode, "inputFormat": INPUT_FORMAT, "resultFormat": RESULT_FORMAT}
                       for name, mode in (("update", "strict-command"), ("query", "fresh-query"), ("scan", "fresh-query"))],
    }
    files["transaction-binding.json"] = json.dumps(declaration, indent=2).encode() + b"\n"


def package_companion(output: Path, project: dict, files: dict[str, bytes]) -> tuple[str, str, str] | None:
    """Carry the captured companion as an asset without changing old manifests."""
    raw = files.get("transaction-binding.json")
    if raw is None:
        return None
    if len(raw) > 131072:
        raise ValueError("transaction companion byte limit")
    from tools.rust_capsule_project import decode_json
    declaration = decode_json(raw)
    required = {"apiVersion", "kind", "capsule", "deployment", "binding", "profile", "hostAbiDigest",
                "namespace", "stateSchema", "operations"}
    if (not isinstance(declaration, dict) or set(declaration) != required
            or declaration["apiVersion"] != "latent.dev/v1" or declaration["kind"] != "TransactionBinding"
            or declaration["capsule"] != project["service"] or declaration["deployment"] != project["name"]
            or declaration["profile"] != "lsf-transaction-v1"):
        raise ValueError("transaction companion must explicitly link the captured capsule/deployment")
    # Semantic/profile/namespace authority validation is the real host admission
    # boundary. Source packaging carries the bytes; it never approves them.
    with (output / "transaction-binding.json").open("xb") as stream:
        stream.write(raw)
    return ("transaction-binding.json", "asset", "application/vnd.latent.transaction-binding.v1+json")
