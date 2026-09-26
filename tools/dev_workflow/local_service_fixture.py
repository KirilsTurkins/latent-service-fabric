"""One explicitly trusted authored callee, deployed on the caller's owned node."""
from pathlib import Path
import re
import secrets

from . import build, paths, project, snapshot, state
from .common import DevError, decode, identifier, members, require, sha

PROVIDER = ("latent:service/invoke@0.1.0", "lsf-local-service-invocation-v1", "call", "service")
CHILD = "test-local-service"


def validate(value: dict) -> dict:
    members(value, {"service", "deployment", "contract", "project", "recipeSha256"})
    require(isinstance(value["service"], str)
            and re.fullmatch(r"[a-z][a-z0-9-]*/[a-z][a-z0-9-]*", value["service"]), "local-fixture-service")
    identifier(value["deployment"])
    require(isinstance(value["contract"], str) and len(value["contract"]) <= 128
            and re.fullmatch(r"[a-z][a-z0-9-]*:[a-z][a-z0-9-]*/[a-z][a-z0-9-]*@[0-9]+\.[0-9]+\.[0-9]+", value["contract"]),
            "local-fixture-contract")
    paths.relative(value["project"])
    sha(value["recipeSha256"])
    return value


def prepare(root: Path, descriptor: dict, tools: Path, fixture: dict) -> dict:
    fixture = validate(fixture)
    require(root.name.startswith("test-") and fixture["service"] != descriptor["service"],
            "disposable-distinct-local-service-required")
    source, _ = build.accepted(root, state.load(root, "project.json"))
    # Explicit fixture consent includes this exact additional recipe hash. The
    # selected source remains beneath the caller's verified input snapshot.
    raw = paths.read(source, fixture["project"] + "/latent.project.json")
    child_descriptor = project.validate(decode(raw))
    require(project.trust_identity(child_descriptor) == fixture["recipeSha256"]
            and child_descriptor["tenant"] == descriptor["tenant"]
            and child_descriptor["service"] == fixture["service"], "local-fixture-recipe-or-scope-changed")
    child_source = source / fixture["project"]
    record, content = snapshot.observe(child_source, child_descriptor["inputRoots"], tuple(child_descriptor["exclude"]))
    child = root / CHILD
    if not child.exists():
        paths.new_directory(child)
        paths.new_directory(child / "snapshots")
    paths.private_root(child)
    selected_source = child / "snapshots" / record["identity"][7:]
    if not selected_source.exists():
        snapshot.materialize(selected_source, record, content)
    saved = {"descriptor": child_descriptor, "trust": fixture["recipeSha256"],
             "source": str(selected_source), "snapshot": record["identity"]}
    if (child / "project.json").exists():
        require(state.load(child, "project.json") == saved, "local-fixture-project-changed-use-new-workspace")
    else:
        state.atomic(child, "project.json", saved)
    from .helper import installation
    _layout, current = installation(root)
    from . import build_control
    with build_control.session(child, secrets.token_hex(16)) as control:
        receipt = build.execute(child, selected_source, child_descriptor, tools,
                                trusted=fixture["recipeSha256"], cli=current / "bin/latent", control=control)
    built, _ = build.accepted(child, saved)
    deployment = decode(paths.read(built, child_descriptor["artifacts"]["deployment"]))
    require(deployment["metadata"]["name"] == fixture["deployment"]
            and deployment["spec"]["service"] == fixture["service"], "local-fixture-deployment-target")
    result = {"fixture": fixture, "source": receipt["source"], "attempt": receipt["attempt"],
              "component": receipt["artifacts"]["component"], "package": receipt["package"]}
    if (root / "local-service-build.json").exists():
        require(state.load(root, "local-service-build.json") == result, "local-fixture-build-changed")
    state.atomic(root, "local-service-build.json", result)
    return result


def signing_input(root: Path) -> tuple[Path, dict, dict]:
    planned = state.load(root, "local-service-build.json")
    fixture = validate(planned["fixture"])
    if (root / "test-profile.json").exists():
        require(state.load(root, "test-profile.json").get("fixtures", {}).get("localService") == fixture,
                "local-fixture-selection-changed")
    child = root / CHILD
    saved = state.load(child, "project.json")
    source, receipt = build.accepted(child, saved)
    require(saved["trust"] == fixture["recipeSha256"] and saved["descriptor"]["service"] == fixture["service"]
            and planned["source"] == receipt["source"] and planned["attempt"] == receipt["attempt"]
            and planned["component"] == receipt["artifacts"]["component"] and planned["package"] == receipt["package"],
            "local-fixture-build-changed")
    return source, saved["descriptor"], receipt


def deploy(root: Path, *, deadline: float) -> dict:
    from . import helper
    signing_input(root)
    return helper.deploy(root / CHILD, runtime_root=root, signing_root=root, deadline=deadline)


def observe(root: Path, cli) -> dict:
    from . import node_tests
    _source, descriptor, receipt = signing_input(root)
    pending = pending_operation(root)
    if pending is not None:
        raise DevError("recover-original-local-service-operation-before-use", uncertain=True)
    deployed, revision, _grants = node_tests.target(root / CHILD, descriptor, receipt, cli)
    fixture = state.load(root, "local-service-build.json")["fixture"]
    require(deployed["deployment"] == fixture["deployment"], "local-fixture-selected-deployment")
    return {"fixture": fixture, "source": receipt["source"], "artifacts": receipt["artifacts"],
            "package": receipt["package"], "deployment": deployed, "expectedRevision": revision}


def initialized(value: dict, providers: dict | None) -> bool:
    fixture = validate(value)
    entry = (providers or {}).get("localService", {})
    return (entry.get("capability") == PROVIDER[0] and entry.get("profile") == PROVIDER[1]
            and entry.get("service") == fixture["service"] and entry.get("configurationEpoch") == "1")


def pending_operation(root: Path) -> dict | None:
    child = root / CHILD
    operations = state.load(child, "operations.json") if (child / "operations.json").exists() else {}
    pending = operations.get("pending")
    return {key: pending[key] for key in ("kind", "id", "requestDigest")} if pending else None


def purge(root: Path) -> None:
    from . import build_cache
    from tools.native_runtime import files
    child = root / CHILD
    if not child.exists():
        return
    paths.private_root(child)
    require(root.name.startswith("test-") and (child / "project.json").exists()
            and not (child / "runtime").exists(), "local-fixture-cleanup-owner-required")
    saved = state.load(child, "project.json")
    project.validate(saved["descriptor"])
    require(saved["trust"] == project.trust_identity(saved["descriptor"]), "local-fixture-cleanup-recipe-owner")
    builds = list((child / "builds").iterdir()) if (child / "builds").exists() else []
    require(len(builds) <= build_cache.MAX_ATTEMPTS, "local-fixture-build-cache-limit")
    for attempt in builds:
        require(build_cache.owner(attempt)["state"] not in {"running", "uncertain"},
                "local-fixture-build-cleanup-unconfirmed")
    files.remove_tree(child, maximum=(build_cache.MAX_ENTRIES + 8) * build_cache.MAX_ATTEMPTS + 32768)
    if (root / "local-service-build.json").exists():
        paths.read(root, "local-service-build.json")
        (root / "local-service-build.json").unlink()
