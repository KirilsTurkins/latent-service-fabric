"""Explicit authenticated compiler installation into one private Linux workspace."""
from pathlib import Path
import re
import time

from . import assets, bundle, paths, project, state, tool_inventory
from .common import HOST_ABI, decode, digest, members, require, sha

MAX_SETS = 2
MAX_ENTRIES = bundle.MAX_ENTRIES * 32 + 16
RELEASE = {"developer-bundle.json", "SHA256SUMS", "attestation.json"}
TRUST = {"publisher-policy.json", "trusted_root.jsonl", "gh"}


def selection(value: dict) -> dict:
    members(value, {"schemaVersion", "directory", "bundle", "inventorySha256", "language", "ownerIssue",
                    "sourceCommit", "version", "host", "hostAbi", "publisherAuthenticated", "publisherPolicySha256"})
    require(value["schemaVersion"] == "latent.dev.tools-selection.v1" and value["publisherAuthenticated"] is True,
            "authenticated-guest-tools-required")
    require(value["language"] in project.LANGUAGES and value["ownerIssue"] == project.LANGUAGES[value["language"]],
            "guest-tool-owner")
    require(value["host"] == "linux-x86_64" and value["hostAbi"] == HOST_ABI, "guest-tool-target")
    require(isinstance(value["sourceCommit"], str) and re.fullmatch(r"[a-f0-9]{40}", value["sourceCommit"]),
            "guest-tool-source")
    sha("sha256:" + value["bundle"])
    sha(value["inventorySha256"])
    sha(value["publisherPolicySha256"])
    require(isinstance(value["version"], str) and 0 < len(value["version"]) <= 128, "guest-tool-version")
    directory = value["directory"]
    require(isinstance(directory, str) and directory.startswith("/") and len(directory) <= 4096
            and directory.endswith("/tools/" + value["bundle"] + "/payload"), "guest-tool-directory")
    paths.relative(directory[1:])
    return value


def selected_root(workspace: Path, descriptor: dict) -> str:
    require((workspace / "tool-selection.json").exists(), "install-matching-guest-tools-or-select-tool-root")
    value = selection(state.load(workspace, "tool-selection.json"))
    require(descriptor["language"] == value["language"] and descriptor["template"]["revision"] == value["sourceCommit"]
            and descriptor["build"].get("inventory") == {"path": "guest-tools.json", "sha256": value["inventorySha256"]},
            "installed-tools-do-not-match-project-pins")
    return value["directory"]


def inputs(workspace: Path, connection, value: dict) -> dict:
    members(value, {"schemaVersion", "bundleDirectory", "version", "language", "publisherPolicy", "trustedRoot",
                    "verifier", "verifierSha256", "allowCandidate", "consent"}, {"resume"})
    require(value["schemaVersion"] == "latent.dev.tool-inputs.v1" and value["consent"] is True,
            "explicit-guest-tools-install-consent-required")
    require(value["language"] in project.LANGUAGES and type(value["allowCandidate"]) is bool
            and type(value.get("resume", False)) is bool, "guest-tool-inputs")
    sources = {"trust/" + name: paths.absolute(Path(value[key])) for key, name in (
        ("publisherPolicy", "publisher-policy.json"), ("trustedRoot", "trusted_root.jsonl"), ("verifier", "gh"))}
    raw_policy = paths.read(sources["trust/publisher-policy.json"].parent, sources["trust/publisher-policy.json"].name)
    policy = bundle.policy(decode(raw_policy), value["version"], allow_candidate=value["allowCandidate"])
    release = paths.absolute(Path(value["bundleDirectory"]))
    expected = bundle.manifest(decode(paths.read(release, "developer-bundle.json", bundle.MAX_MANIFEST), bundle.MAX_MANIFEST),
        target="linux-x86_64", version=value["version"], commit=policy["sourceCommit"])
    sources.update({"release/" + name: release / name for name in RELEASE | {expected["archive"]["name"]}})
    require(paths.digest_file(sources["trust/gh"].parent, sources["trust/gh"].name, assets.MAX_ASSET)[0]
            == sha(value["verifierSha256"]), "independent-linux-verifier-digest-mismatch")
    transferred = assets.transfer(connection, sources)
    result = selection(connection.call("install-tools", {"assetIdentity": transferred["identity"],
        **{key: value[key] for key in ("version", "language", "verifierSha256", "allowCandidate", "consent")},
        "resume": value.get("resume", False)}, timeout=615))
    require(result["bundle"] == expected["archive"]["sha256"][7:] and result["version"] == value["version"]
            and result["sourceCommit"] == policy["sourceCommit"] and result["language"] == value["language"]
            and result["publisherPolicySha256"] == digest(raw_policy), "guest-tool-install-response-identity")
    entry = next((item for item in expected["files"] if item["path"] == "guest-tools.json"), None)
    require(entry is not None and result["inventorySha256"] == entry["sha256"], "guest-tool-install-response-inventory")
    state.atomic(workspace, "tool-selection.json", result)
    return result


def install(root: Path, arguments: dict) -> dict:
    """Called under the workspace lock; never execute a compiler during install."""
    members(arguments, {"assetIdentity", "version", "language", "verifierSha256", "allowCandidate", "consent", "resume"})
    require(arguments["consent"] is True and type(arguments["resume"]) is bool
            and type(arguments["allowCandidate"]) is bool, "explicit-guest-tools-install-consent-required")
    language = arguments["language"]
    require(language in project.LANGUAGES, "unsupported-guest-language")
    deadline = time.monotonic() + 600
    def check():
        require(time.monotonic() < deadline, "guest-tool-install-deadline")
    source = assets.directory(root, arguments["assetIdentity"])
    transferred = assets.manifest(state.load(source, "complete.json"))
    require(transferred["identity"] == arguments["assetIdentity"], "offline-input-identity")
    for entry in transferred["files"]:
        require(paths.digest_file(source, entry["path"], assets.MAX_ASSET, check=check) == (entry["sha256"], entry["size"]),
                "offline-input-content-mismatch")
    selected = bundle.authenticate(source / "release", source / "trust/publisher-policy.json",
        source / "trust/trusted_root.jsonl", source / "trust/gh", arguments["verifierSha256"],
        target="linux-x86_64", version=arguments["version"], allow_candidate=arguments["allowCandidate"])
    require({entry["path"] for entry in transferred["files"]} == {"release/" + name for name in RELEASE | {selected["archive"]["name"]}}
            | {"trust/" + name for name in TRUST}, "guest-tool-input-inventory")
    identity = selected["archive"]["sha256"][7:]
    metadata = {"schemaVersion": "latent.dev.tool-install.v1", "bundle": identity,
                "language": language, "sourceCommit": selected["sourceCommit"], "version": selected["version"]}
    cache = root / "tools"
    if not cache.exists():
        paths.new_directory(cache)
    paths.private_root(cache)
    slot = cache / identity
    if slot.exists():
        owner = state.load(slot, "owner.json")
        require({key: item for key, item in owner.items() if key != "state"} == metadata
                and owner.get("state") in {"extracting", "ready"}, "guest-tool-install-owner")
        if owner["state"] == "extracting":
            require(arguments["resume"], "interrupted-tool-install-requires-explicit-resume")
            if (slot / "payload").exists():
                from tools.native_runtime.files import remove_tree
                remove_tree(slot / "payload", maximum=MAX_ENTRIES)
    else:
        require(sum(1 for _ in cache.iterdir()) < MAX_SETS, "guest-tool-cache-full-purge-workspace-explicitly")
        paths.new_directory(slot)
        state.atomic(slot, "owner.json", {**metadata, "state": "extracting"})
    payload = slot / "payload"
    if payload.exists():
        bundle.verify_cache(payload, selected, check=check)
    else:
        bundle.extract(source / "release", selected, payload, check=check)
    entry = next((item for item in selected["files"] if item["path"] == "guest-tools.json"), None)
    require(entry is not None, "guest-tool-inventory-required")
    raw = paths.read(payload, "guest-tools.json", tool_inventory.MAX_DOCUMENT)
    require((digest(raw), len(raw)) == (entry["sha256"], entry["size"]), "guest-tool-inventory-digest")
    inventory = tool_inventory.validate(decode(raw, tool_inventory.MAX_DOCUMENT), language, project.LANGUAGES[language], "linux-x86_64")
    require(inventory["sourceCommit"] == selected["sourceCommit"], "guest-tool-inventory-source")
    files = {item["path"]: item for item in selected["files"]}
    require(all(item["path"] in files and (item["sha256"], item["size"]) ==
                (files[item["path"]]["sha256"], files[item["path"]]["size"]) for item in inventory["files"]),
            "guest-tool-companion-outside-bundle")
    check()
    result = selection({"schemaVersion": "latent.dev.tools-selection.v1", "directory": str(payload), "bundle": identity,
        "inventorySha256": entry["sha256"], "language": language, "ownerIssue": project.LANGUAGES[language],
        "sourceCommit": selected["sourceCommit"], "version": selected["version"], "host": "linux-x86_64", "hostAbi": HOST_ABI,
        "publisherAuthenticated": True, "publisherPolicySha256": digest(paths.read(source / "trust", "publisher-policy.json"))})
    state.atomic(slot, "owner.json", {**metadata, "state": "ready"})
    state.atomic(root, "tool-selection.json", result)
    return result


def purge(root: Path) -> None:
    from tools.native_runtime.files import remove_tree
    cache = root / "tools"
    if not cache.exists():
        return
    paths.private_root(cache)
    slots = list(cache.iterdir())
    require(len(slots) <= MAX_SETS, "guest-tool-cache-entry-limit")
    for slot in slots:
        sha("sha256:" + slot.name)
        value = state.load(slot, "owner.json")
        require(value.get("schemaVersion") == "latent.dev.tool-install.v1" and value.get("bundle") == slot.name
                and value.get("state") in {"extracting", "ready"}, "guest-tool-install-owner")
    remove_tree(cache, maximum=MAX_SETS * MAX_ENTRIES)
