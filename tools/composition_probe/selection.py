"""Freeze intended tuples from original signed bytes and authorized inspections."""
from copy import deepcopy

from tools.dev_workflow import preflight
from tools.dev_workflow.common import digest, encode
from tools.phase2_operator_process import require, write_json

from .source import java_component


def freeze(builds, releases, snapshots, output, profile, *, grant_digest=None):
    """Keep original declarations separate from the later command's observations.

    Snapshots choose deployment identities, engine keys and configured provider
    pins. Contract declarations come only from the original signed package and
    its independent build, never from the RPC's projected preparation surface.
    These declarations grant no execution authority.
    """
    require(1 <= len(snapshots) <= 8, "composition-probe-selection-bound")
    components, providers, policies, tenants = [], {}, {}, set()
    for name, original in snapshots.items():
        require(original["schemaVersion"] == 1 and original["stateName"] == "coherent"
                and original["liveGrantsChecked"] is False and len(original["candidates"]) == 1,
                "composition-probe-original-selection-required")
        row = original["candidates"][0]
        selected = {key: original[key] for key in ("service", "route", "contract", "function")}
        selected.update(revision=row["revisionId"], publicationId=row["publication"]["id"],
                        deploymentId=row["deploymentId"], deploymentGeneration=row["deploymentGeneration"])
        tenants.add(original["tenant"])
        require(row["publication"]["tenant"] == original["tenant"], "composition-probe-original-tenant")
        component = java_component(releases / ("java-http-" + name) / "package",
                                   builds / name, selected, output, name)
        require(component["componentDigest"] == row["componentDigest"]
                and component["packageDigest"] == row["packageDigest"],
                "composition-probe-original-publication-mismatch")
        prepared = row["preparation"]
        engine = prepared["engineConfigurationDigest"]
        if engine is None and prepared["diagnostic"] is not None:
            engine = "blake3:" + prepared["diagnostic"]["profileDigest"]
        require(engine is not None, "composition-probe-original-engine-required")
        component["engineConfigurationDigest"] = engine
        components.append(component)
        for dependency in row["dependencies"]:
            provider = {"contract": dependency["capability"],
                "providerProfile": dependency["providerProfile"],
                "configurationDigest": dependency["configurationDigest"],
                "configurationEpoch": dependency["providerConfigurationEpoch"],
                "bindingId": dependency["binding"]["id"], "bindingDigest": dependency["binding"]["digest"],
                "policyIds": sorted(policy["id"] for policy in dependency["policies"])}
            key = provider["contract"]
            require(key not in providers or providers[key] == provider, "composition-probe-ambiguous-provider-intent")
            providers[key] = provider
            for policy in dependency["policies"]:
                declaration = {key: policy[key] for key in ("id", "digest")}
                require(policy["id"] not in policies or policies[policy["id"]] == declaration,
                        "composition-probe-ambiguous-policy-intent")
                policies[policy["id"]] = declaration
    require(len(tenants) == 1, "composition-probe-mixed-tenant-selection")
    triggers = [{"kind": "http" if row["target"]["contract"] == preflight.WEB_CONTRACT else "typed",
        "component": row["id"], "contract": row["target"]["contract"], "function": row["target"]["function"]}
        for row in components]
    edges = []
    if grant_digest is not None:
        require(set(snapshots) == {"domain", "adapter"}, "composition-probe-original-child-pair-required")
        child = next(row for row in components if row["id"] == "domain")
        edges.append({"from": "adapter", "to": "domain", "contract": child["target"]["contract"],
            "function": child["target"]["function"], "declaredGrantDigest": grant_digest,
            "requestBudget": deepcopy(child["budget"])})
    value = preflight.validate({"schemaVersion": preflight.FORMAT, "tenant": tenants.pop(),
        "nodeProfile": deepcopy(profile), "components": components, "triggers": triggers,
        "serviceEdges": edges, "providers": list(providers.values()), "policies": list(policies.values())})
    write_json(output / "original-selection.json", {"compositionDigest": digest(encode(value)),
        "originalInspectionsDigest": digest(encode(snapshots)), "authorityCreated": False,
        "contractSource": "original-signed-OCI-layers-and-independent-build"})
    return value
