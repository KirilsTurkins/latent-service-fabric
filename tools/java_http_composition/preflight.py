"""Observe the delivered native frontend against the owner's actual signed pair."""
from pathlib import Path
import re

from tools.build_dev_frontend import preflight_resources
from tools.composition_probe.frontend import Frontend
from tools.composition_probe.schedule import Schedule
from tools.composition_probe.selection import freeze
from tools.dev_workflow.common import digest
from tools.dev_workflow.composition_contract import support_matrix
from tools.java_http_composition.node import SERVICE_CAPABILITY
from tools.phase2_operator_process import read_json, require, write_json
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_project import fresh


class NativeFrontend:
    """One original native build; its receipt remains a build observation."""
    def __init__(self, binary: Path, build_receipt: Path):
        self.binary, self.build_receipt = binary, build_receipt
        self.binary_identity = file_identity(binary, 256 * 1024 * 1024)
        self.build_identity = file_identity(build_receipt, 262144)
        built = read_json(build_receipt)
        require(built["schemaVersion"] == "latent.dev.frontend-build.v1"
            and re.fullmatch(r"[0-9a-f]{40}", built["sourceCommit"])
            and built["sourceDirty"] is False
            and built["frontendSha256"] == self.binary_identity["sha256"],
            "java-native-frontend-original-build-required")
        expected = [{"path": name, "sha256": digest(raw), "size": len(raw)}
                    for name, raw in preflight_resources()]
        require(built["preflightResources"] == expected,
                "java-native-frontend-current-contract-resources-required")
        self.observation = {"schemaVersion": built["schemaVersion"],
            "sourceCommit": built["sourceCommit"], "sourceDirty": False,
            "target": built["target"], "frontend": self.binary_identity,
            "buildReceipt": self.build_identity, "preflightResources": expected,
            "publisherAuthenticated": built["publisherAuthenticated"],
            "qualification": built["qualification"]}

    @classmethod
    def authenticate_release(cls, configuration, output: Path):
        """Use the original authenticated release without inventing a build receipt.

        The maintained bootstrap verifies the independently approved publisher
        policy and original Sigstore inventory before extracting executable code.
        The signed file inventory then binds the four exact embedded contracts.
        This observation establishes artifact identity; execution is recorded by
        the separate finite preflight schedule.
        """
        from tools.dev_packaged_bootstrap import authenticate, extract

        output = fresh(output)
        manifest, verification = authenticate(configuration, output, target="linux-x86_64")
        release = Path(configuration["artifacts"]["linux"])
        binary = extract(release, manifest, output / "frontend")
        expected = [{"path": name, "sha256": digest(raw), "size": len(raw)}
                    for name, raw in preflight_resources()]
        inventory = {row["path"]: row for row in manifest["files"]}
        for row in expected:
            embedded = "bin/_internal/tools/dev_workflow/data/" + Path(row["path"]).name
            require(embedded in inventory
                and inventory[embedded]["sha256"] == row["sha256"]
                and inventory[embedded]["size"] == row["size"],
                "java-native-frontend-current-contract-resources-required")
        selected = cls.__new__(cls)
        selected.binary, selected.build_receipt = binary, release / "developer-bundle.json"
        selected.binary_identity = file_identity(binary, 256 * 1024 * 1024)
        selected.build_identity = file_identity(selected.build_receipt, 262144)
        selected.observation = {"schemaVersion": "latent.java-http.authenticated-frontend.v1",
            "sourceCommit": manifest["sourceCommit"], "target": manifest["target"],
            "frontend": selected.binary_identity, "originalManifest": selected.build_identity,
            "originalArchive": file_identity(release / manifest["archive"]["name"], 1024 * 1024 * 1024),
            "preflightResources": expected, "publisherAuthenticated": True,
            "authentication": verification, "executionQualified": False}
        write_json(output / "authenticated-frontend.json", selected.observation)
        return selected

    def unchanged(self):
        require(self.binary_identity == file_identity(self.binary, 256 * 1024 * 1024)
            and self.build_identity == file_identity(self.build_receipt, 262144),
            "java-native-frontend-original-build-changed")

    def schedule(self, client, releases, output, snapshots, node_config, *, former=False):
        self.unchanged()
        output = fresh(output)
        settings = read_json(node_config)
        body_limits = support_matrix()["bufferedHttpLimits"]
        profile = {"id": "former-http-global-values-v1" if former else "http-java-v1",
            "javaGuest": settings["engine"]["javaGuest"],
            "maximumWirePayloadBytes": str(settings["limits"]["maximumPayloadBytes"]),
            **{name: body_limits[name] for name in ("maximumRequestBodyBytes", "maximumResponseBodyBytes")}}
        grant_digest = None
        if not former:
            dependencies = snapshots["adapter"]["candidates"][0]["dependencies"]
            selected = [policy["digest"] for dependency in dependencies
                if dependency["capability"] == SERVICE_CAPABILITY
                for policy in dependency["policies"] if policy["id"] == "java-domain-allow"]
            require(len(selected) == 1, "java-native-frontend-original-child-policy-required")
            grant_digest = selected[0]
        original = freeze(releases.parent / "builds", releases, snapshots, output, profile,
                          grant_digest=grant_digest)
        write_json(output / "native-frontend-build-observation.json", self.observation)
        frontend = Frontend(self.binary, self.binary_identity["sha256"], output, client)
        schedule = Schedule(frontend, original)
        return schedule, {"frontendBuild": self.observation, "entry": "standalone",
            "contractSource": "original-signed-OCI-layers-and-independent-build",
            "cases": frontend.cases, "executionQualified": False}
