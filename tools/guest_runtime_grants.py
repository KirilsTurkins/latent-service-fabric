"""Explicit, finite runtime grants for managed-language authoring experiments."""
from tools.phase2_operator_process import require, write_json
from tools.rust_capsule_node import call, deploy

RUNTIME = {
    "clockMonotonic": ("latent:clock/monotonic@0.1.0", "activation-monotonic-v1", "now-nanos", "clock"),
    "clockWall": ("latent:clock/wall@0.1.0", "activation-wall-v1", "now-unix-millis", "clock"),
    "random": ("latent:random/random@0.1.0", "system-random-v1", "u64-value", "random"),
}


def configure(settings, templates):
    for name, (contract, _profile, _operation, _kind) in RUNTIME.items():
        settings["providers"][name] = {"identity": {"id": name, "tenant": "examples", "service": "runtime-host", "epoch": 1}}
        for template in sorted(templates):
            settings["providers"]["bindings"].append({"name": name + "-" + template,
                "tenant": "examples", "consumerService": "examples/my-" + template, "providerService": "runtime-host",
                "contract": contract, "providerBinding": name + "-installed"})
    require(len(settings["providers"]["bindings"]) <= 16, "runtime-provider-binding-bound")
    settings["audit"].update(records=4096, diskBytes=67108864)


def grant(client, node, fixture, targets, publications, result):
    denied = call(client, targets["greeting"], "greeting", "greet", ["Ada"], "runtime-grant-denied")
    require(denied["exitCode"] == 4 and denied["response"]["error"]["code"] == "permission-denied",
            "runtime-imports-require-explicit-grants")
    result["runtimeGrantDenied"] = denied
    grants = []
    for name, (capability, profile, operation, kind) in RUNTIME.items():
        installed = [row for row in node.startup_record["providers"] if row["id"] == name]
        require(len(installed) == 1 and installed[0]["capability"] == capability and installed[0]["profile"] == profile,
                "runtime-provider-installation-identity")
        descriptor = installed[0]
        binding = client.directory / (name + "-binding.json")
        write_json(binding, {"formatVersion": 1, "tenant": "examples", "capability": capability,
            "providerProfile": profile, "configurationDigest": descriptor["configurationDigest"],
            "configurationEpoch": 1, "restriction": {"operations": [operation]}})
        client.call("policy", "--kind", "provider-binding", "apply", "--id", name + "-installed", "--file", binding,
                    "--operation-id", "install-" + name, "--expected-generation", "0")
        policy = client.directory / (name + "-policy.json")
        write_json(policy, {"formatVersion": 1, "tenant": "examples", "rules": [{
            "id": "runtime", "effect": "allow", "principals": [{"kind": "administrator", "subject": "workflow-operator"}],
            "services": sorted(target["service"] for target in targets.values()),
            "publications": sorted(publications.values()), "capability": capability, "operations": [operation],
            "resources": {"kind": kind}, "ceiling": {"operations": 4096, "inputBytes": 8 if kind == "random" else 0,
                "outputBytes": 32768, "wallTimeMillis": 5000}}]})
        client.call("policy", "apply", "--id", name + "-allow", "--file", policy,
                    "--operation-id", "grant-" + name, "--expected-generation", "0")
        grants.append({"capability": capability, "policy": name + "-allow"})
    for template, target in list(targets.items()):
        targets[template] = deploy(client, fixture / ("my-" + template) / "deployment.json", publications[template],
            generation=str(target["generation"]), grants=grants)
