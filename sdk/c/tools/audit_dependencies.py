from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import urllib.request


LOCK = Path(__file__).resolve().parents[1] / "dependencies.lock.json"


def components(lock):
    result = dict(lock)
    for item in lock.values():
        for bundled in item.get("bundled", []):
            if bundled["name"] in result:
                raise ValueError("duplicate dependency component")
            result[bundled["name"]] = bundled
    return result


def queries(lock):
    result = []
    for name, item in components(lock).items():
        if "commit" in item:
            result.append((name, {"commit": item["commit"]}))
        else:
            result.append((name, {"package": {"name": name, "ecosystem": "PyPI"}, "version": item["version"]}))
        if name == "nanopb":
            result.append((name, {"package": {"name": name, "ecosystem": "PyPI"}, "version": item["version"]}))
    return result


def graph(lock, timestamp):
    selected = components(lock)
    entries = []
    for name, item in selected.items():
        properties = [{"name": "latent:dependency-role", "value": item["role"]}]
        if "commit" in item:
            properties.append({"name": "latent:source-commit", "value": item["commit"]})
        for path, digest in item.get("files", {}).items():
            properties.append({"name": "latent:bundled-file-sha256:" + path, "value": digest})
        entry = {"type": "library", "bom-ref": "latent-c:" + name, "name": name,
                 "version": item["version"], "purl": item["purl"],
                 "externalReferences": [{"type": "distribution" if "sha256" in item else "vcs", "url": item["url"]}],
                 "properties": properties}
        if "sha256" in item:
            entry["hashes"] = [{"alg": "SHA-256", "content": item["sha256"]}]
        entries.append(entry)
    edges = [{"ref": "latent-sdk-c", "dependsOn": ["latent-c:" + name for name in lock]}]
    for name, item in selected.items():
        children = ["hpack", "hyperframe"] if name == "h2" else ["protobuf"] if name == "nanopb" else []
        children.extend(bundled["name"] for bundled in item.get("bundled", []))
        edges.append({"ref": "latent-c:" + name, "dependsOn": ["latent-c:" + child for child in children]})
    return {"bomFormat": "CycloneDX", "specVersion": "1.6", "version": 1,
            "metadata": {"timestamp": timestamp, "component": {"type": "library", "bom-ref": "latent-sdk-c", "name": "latent-sdk-c"},
                         "properties": [{"name": "latent:graph-scope", "value": "Locked artifacts and the C runtime source closure; prebuilt generator binary closure and OS/compiler inventory are separate"}]},
            "components": entries, "dependencies": edges}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    lock_bytes = LOCK.read_bytes()
    lock = json.loads(lock_bytes)
    selected = queries(lock)
    body = json.dumps({"queries": [query for _, query in selected]}).encode()
    request = urllib.request.Request("https://api.osv.dev/v1/querybatch", data=body,
                                     headers={"Content-Type": "application/json", "User-Agent": "latent-c-dependency-audit"})
    with urllib.request.urlopen(request, timeout=30) as response:
        data = response.read(1048577)
    if len(data) > 1048576:
        raise RuntimeError("OSV response exceeds audit bound")
    findings = json.loads(data).get("results")
    if not isinstance(findings, list) or len(findings) != len(selected) or not all(isinstance(item, dict) for item in findings):
        raise RuntimeError("incomplete OSV response")
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    records = [{"component": name, "query": query, "response": finding}
               for (name, query), finding in zip(selected, findings, strict=True)]
    complete = not any(item.get("next_page_token") for item in findings)
    vulnerabilities = sorted({vulnerability["id"] for item in findings for vulnerability in item.get("vulns", [])})
    report = {"schemaVersion": "latent.c.dependency-audit.v1", "queriedAt": timestamp,
              "service": "https://api.osv.dev/v1/querybatch", "lockSha256": hashlib.sha256(lock_bytes).hexdigest(),
              "complete": complete, "vulnerabilityIds": vulnerabilities, "queries": records,
              "limitation": "No returned findings is not proof of safety or index coverage. Independently review upstream advisories; prebuilt generator binary closure and OS/compiler inventory remain separate."}
    for path, value in ((args.graph, graph(lock, timestamp)), (args.report, report)):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    if vulnerabilities or not complete:
        raise SystemExit("C dependency advisory review required: " + ",".join(vulnerabilities))
    print(f"Fresh OSV audit: {len(selected)} queries, {len(components(lock))} locked components, no returned findings")
    print(f"C dependency graph: {args.graph} (CycloneDX 1.6 JSON, role-labelled components and edges)")


if __name__ == "__main__":
    main()
