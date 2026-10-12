"""Actual source-bound generator failures retained before real Java execution."""
from copy import deepcopy
from pathlib import Path
from tools.java_http_generation.project import check, rendered
from tools.rust_capsule_project import canonical, fresh, read_json, snapshot, write_json


def capture(source: Path, destination: Path):
    destination = fresh(destination)
    for name, data in snapshot(source).items():
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return destination


def qualify(domain: Path, selection: Path, adapter: Path, output: Path) -> dict:
    output = fresh(output)
    result = {"schemaVersion": "latent.java-http.generation-cases.v1", "cases": {}}
    original = read_json(selection)

    def rejected(name, expected, function):
        try:
            function()
        except ValueError as error:
            if expected not in str(error): raise
            result["cases"][name] = {"outcome": "rejected", "reason": str(error)}
            return
        raise ValueError("generator-negative-case-accepted: " + name)

    try:
        for name in ("private-admin", "publishing", "provider-event", "duplicate-route", "duplicate-client", "wrong-contract",
                     "oversized-child-deadline", "noninteger-child-deadline"):
            changed = deepcopy(original)
            if name in original["privateOperations"]:
                changed["routes"].append({"method": "GET", "path": "/api/" + name, "operation": name, "clientName": "forbidden"})
                expected = "private operation"
            elif name.endswith("child-deadline"):
                changed["routes"][0]["childDeadlineOffsetMillis"] = 60001 if name.startswith("oversized") else True
                expected = "childDeadlineOffsetMillis must be an integer from zero to 60000"
            elif name == "wrong-contract":
                changed["domain"]["contract"] = changed["domain"]["contract"].replace("@1.0.0", "@2.0.0")
                expected = "not an actual nonempty domain export"
            else:
                route = deepcopy(changed["routes"][0])
                route["clientName" if name == "duplicate-route" else "path"] = "duplicate" if name == "duplicate-route" else "/api/duplicate"
                changed["routes"].append(route)
                expected = "duplicate route or client name"
            path = output / (name + ".json")
            path.write_bytes(canonical(changed))
            rejected(name, expected, lambda: rendered(domain, path))
        stale_adapter = capture(adapter, output / "stale-adapter")
        source = stale_adapter / "src/dev/latent/app/Capsule.java"
        source.write_bytes(source.read_bytes() + b"\n// edited stale binding\n")
        rejected("stale-generated-source", "stale-generation", lambda: check(domain, selection, stale_adapter))
        stale_domain = capture(domain, output / "stale-domain")
        wit = stale_domain / "wit/world.wit"
        wit.write_bytes(wit.read_bytes().replace(b"sequence-number = u64", b"sequence-number = u32"))
        rejected("stale-domain-type-width", "stale-generation", lambda: check(stale_domain, selection, adapter))
        check(domain, selection, adapter)
        result.update(status="passed", freshAfterFailures=True)
        write_json(output / "generation-cases.json", result)
        return result
    except BaseException as error:
        result.update(status="failed", reason=str(error) if isinstance(error, ValueError) else type(error).__name__)
        write_json(output / "GENERATION-CASES-FAILED.json", result)
        raise
