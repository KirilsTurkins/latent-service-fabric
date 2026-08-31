"""Regression tests for Issue #36's cross-layer Phase 1 contract changes."""

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from tools.validate_phase1_descriptor import (
    GOLDEN,
    normalize_descriptor,
    validate_descriptor,
)


ROOT = Path(__file__).resolve().parents[2]


def load_descriptor_golden() -> dict[str, Any]:
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def descriptor_file(
    descriptor: dict[str, Any], file_name: str
) -> dict[str, Any]:
    for file_descriptor in descriptor["file"]:
        if file_descriptor["name"] == file_name:
            return file_descriptor
    raise AssertionError(f"missing descriptor file {file_name}")


def message(
    file_descriptor: dict[str, Any], message_name: str
) -> dict[str, Any]:
    for candidate in file_descriptor.get("messageType", []):
        if candidate["name"] == message_name:
            return candidate
    raise AssertionError(
        f"missing message {file_descriptor['name']}:{message_name}"
    )


def field(message_descriptor: dict[str, Any], name: str) -> dict[str, Any]:
    for candidate in message_descriptor.get("field", []):
        if candidate["name"] == name:
            return candidate
    raise AssertionError(f"missing field {name}")


def nested_message(
    message_descriptor: dict[str, Any], name: str
) -> dict[str, Any]:
    for candidate in message_descriptor.get("nestedType", []):
        if candidate["name"] == name:
            return candidate
    raise AssertionError(f"missing nested message {name}")


class DescriptorContractTests(unittest.TestCase):
    def test_full_normalized_descriptor_golden_captures_semantic_shape(self) -> None:
        golden = load_descriptor_golden()

        self.assertEqual(normalize_descriptor(golden), golden)
        validate_descriptor(golden, golden)
        self.assertEqual(
            {file_descriptor["name"] for file_descriptor in golden["file"]},
            {
                "latent/control/v1/audit.proto",
                "latent/control/v1/binding.proto",
                "latent/control/v1/capability.proto",
                "latent/control/v1/common.proto",
                "latent/control/v1/contract.proto",
                "latent/control/v1/deployment.proto",
                "latent/control/v1/node.proto",
                "latent/control/v1/policy.proto",
                "latent/control/v1/release.proto",
                "latent/control/v1/route.proto",
                "latent/control/v1/trigger.proto",
                "latent/invocation/v1/invocation.proto",
            },
        )

        invocation = descriptor_file(
            golden, "latent/invocation/v1/invocation.proto"
        )
        invoke_response = message(invocation, "InvokeResponse")
        for name, type_name in (
            ("success", ".latent.invocation.v1.Success"),
            ("declared_error", ".latent.invocation.v1.DeclaredError"),
            ("platform_failure", ".latent.invocation.v1.PlatformError"),
        ):
            outcome_field = field(invoke_response, name)
            self.assertEqual(outcome_field["label"], "LABEL_OPTIONAL")
            self.assertEqual(outcome_field["type"], "TYPE_MESSAGE")
            self.assertEqual(outcome_field["typeName"], type_name)
            self.assertEqual(outcome_field["oneofIndex"], 0)
        self.assertEqual(invoke_response["oneofDecl"][0]["name"], "result")

        cancel_response = message(invocation, "CancelResponse")
        self.assertEqual(field(cancel_response, "disposition")["type"], "TYPE_ENUM")
        self.assertEqual(field(cancel_response, "terminal_state")["oneofIndex"], 0)
        self.assertEqual(cancel_response["oneofDecl"][0]["name"], "_terminal_state")

        error_detail = message(invocation, "ErrorDetail")
        fields_map = nested_message(error_detail, "FieldsEntry")
        self.assertTrue(fields_map["options"]["mapEntry"])
        self.assertEqual(
            fields_map["field"],
            [
                {
                    "jsonName": "key",
                    "label": "LABEL_OPTIONAL",
                    "name": "key",
                    "number": 1,
                    "type": "TYPE_STRING",
                },
                {
                    "jsonName": "value",
                    "label": "LABEL_OPTIONAL",
                    "name": "value",
                    "number": 2,
                    "type": "TYPE_STRING",
                },
            ],
        )

    def test_descriptor_validator_detects_type_cardinality_and_oneof_drift(self) -> None:
        golden = load_descriptor_golden()
        descriptor = copy.deepcopy(golden)
        invocation = descriptor_file(
            descriptor, "latent/invocation/v1/invocation.proto"
        )
        invoke_response = message(invocation, "InvokeResponse")
        declared_error = field(invoke_response, "declared_error")
        declared_error["label"] = "LABEL_REPEATED"
        declared_error["type"] = "TYPE_STRING"
        declared_error.pop("oneofIndex")

        with self.assertRaisesRegex(ValueError, "descriptor contract changed"):
            validate_descriptor(descriptor, golden)

    def test_descriptor_validator_detects_additional_descriptor_drift(self) -> None:
        golden = load_descriptor_golden()
        descriptor = copy.deepcopy(golden)
        invocation = descriptor_file(
            descriptor, "latent/invocation/v1/invocation.proto"
        )
        message(invocation, "InvokeResponse")["field"].append(
            {
                "name": "unsafe_unreviewed_field",
                "number": 99,
                "label": "LABEL_OPTIONAL",
                "type": "TYPE_STRING",
                "jsonName": "unsafeUnreviewedField",
            }
        )

        with self.assertRaisesRegex(ValueError, "descriptor contract changed"):
            validate_descriptor(descriptor, golden)


class SchemaAndSurfaceTests(unittest.TestCase):
    def schema_validator(self, name: str) -> Draft202012Validator:
        document = json.loads((ROOT / "schemas" / name).read_text(encoding="utf-8"))
        return Draft202012Validator(document)

    def test_persistent_schemas_reject_the_legacy_absolute_deadline(self) -> None:
        for schema_name, example_path, limits_path in (
            (
                "capsule-manifest.schema.json",
                ROOT / "examples/echo-contract/capsule.json",
                ("execution", "limits"),
            ),
            (
                "deployment.schema.json",
                ROOT / "examples/echo-contract/deployment.json",
                ("spec", "resources"),
            ),
        ):
            valid = json.loads(example_path.read_text(encoding="utf-8"))
            limits = valid
            for segment in limits_path:
                limits = limits[segment]
            limits["wallDeadlineUnixMillis"] = limits.pop("wallTimeLimitMillis")
            errors = list(self.schema_validator(schema_name).iter_errors(valid))
            self.assertTrue(errors, schema_name)

    def test_route_and_publish_examples_validate_with_the_new_contracts(self) -> None:
        pairs = (
            ("route-snapshot.schema.json", ROOT / "examples/route-snapshot.json"),
            (
                "release-publish.schema.json",
                ROOT / "examples/echo-contract/publish-release.json",
            ),
        )
        for schema_name, example_path in pairs:
            document = json.loads(example_path.read_text(encoding="utf-8"))
            self.assertEqual(
                list(self.schema_validator(schema_name).iter_errors(document)), []
            )

        route = json.loads(
            (ROOT / "examples/route-snapshot.json").read_text(encoding="utf-8")
        )
        self.assertEqual(route["services"][0]["tenant"], "examples")
        self.assertEqual(route["bindings"][0]["consumerTenant"], "examples")
        self.assertEqual(route["bindings"][0]["providerTenant"], "examples")

    def test_wit_and_all_sdk_surfaces_use_the_relative_budget_and_typed_errors(self) -> None:
        context = (ROOT / "wit/platform/context/package.wit").read_text(encoding="utf-8")
        invoke = (
            ROOT / "wit/platform/invocation/package.wit"
        ).read_text(encoding="utf-8")
        self.assertIn("wall-time-limit-millis", context)
        self.assertIn("variant invocation-outcome", invoke)
        self.assertIn("record error-detail", invoke)

        sdk_files = (
            ROOT / "sdk/rust/src/lib.rs",
            ROOT / "sdk/go/latent.go",
            ROOT / "sdk/typescript-client/src/index.ts",
            ROOT / "sdk/dotnet/Latent.Sdk/Abstractions.cs",
            ROOT / "sdk/java-client/src/main/java/dev/latent/sdk/Models.java",
            ROOT / "sdk/c/include/latent/latent.h",
        )
        for path in sdk_files:
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("WallDeadlineUnixMillis", source, path)
            self.assertNotIn("wallDeadlineUnixMillis", source, path)
            self.assertNotIn("wall_deadline_unix_millis", source, path)

    def test_sdk_invocation_status_and_cancellation_surfaces_are_equivalent(self) -> None:
        expected = {
            "sdk/rust/src/lib.rs": (
                "InvocationReceipt",
                "pub consumption: BudgetConsumption",
                "DeclaredInvocationError",
                "PlatformInvocationFailure",
                "pub enum InvocationOutcome",
                "Succeeded(InvokeResponse)",
                "DeclaredError(DeclaredInvocationError)",
                "PlatformFailure(PlatformInvocationFailure)",
                "RetainedInvocationOutcome",
                "ActivationStatus",
                "get_activation",
                "pub enum CancelResponse",
                "AlreadyTerminal(ActivationTerminalState)",
                "ErrorDetail",
            ),
            "sdk/go/latent.go": (
                "InvocationReceipt",
                "Consumption     BudgetConsumption",
                "DeclaredInvocationError",
                "PlatformInvocationFailure",
                "Success         *InvokeResponse",
                "DeclaredError   *DeclaredInvocationError",
                "PlatformFailure *PlatformInvocationFailure",
                "RetainedInvocationOutcome",
                "ActivationStatus",
                "GetActivation",
                "CancelResponse",
                "ErrorDetail",
                "Details   []ErrorDetail",
                "CommittedStateVersion *string",
                "EffectIDs             []string",
            ),
            "sdk/typescript-client/src/index.ts": (
                "InvocationReceipt",
                "readonly consumption: BudgetConsumption",
                'kind: "success"',
                'kind: "declared-error"',
                'kind: "platform-failure"',
                "RetainedInvocationOutcome",
                "ActivationStatus",
                "getActivation",
                "CancelResponse",
                "ErrorDetail",
                "readonly details: readonly ErrorDetail[]",
                "readonly effectIds: readonly string[]",
            ),
            "sdk/dotnet/Latent.Sdk/Abstractions.cs": (
                "InvocationReceipt",
                "BudgetConsumption Consumption",
                "record Succeeded",
                "record DeclaredFailure",
                "record PlatformFailure",
                "RetainedInvocationOutcome",
                "ActivationStatus",
                "GetActivationAsync",
                "CancelResponse",
                "ErrorDetail",
                "IReadOnlyList<ErrorDetail> Details",
                "IReadOnlyList<string> EffectIds",
            ),
            "sdk/java-client/src/main/java/dev/latent/sdk/Models.java": (
                "InvocationReceipt",
                "BudgetConsumption consumption",
                "InvocationSuccess",
                "DeclaredInvocationError",
                "PlatformInvocationFailure",
                "RetainedInvocationOutcome",
                "ActivationStatus",
                "CancelResponse",
                "ErrorDetail",
                "List<ErrorDetail> details",
                "List<String> effectIds",
            ),
            "sdk/java-client/src/main/java/dev/latent/sdk/LatentClient.java": (
                "getActivation",
            ),
            "sdk/c/include/latent/latent.h": (
                "latent_invocation_receipt",
                "latent_budget_consumption consumption",
                "latent_declared_invocation_error",
                "latent_platform_invocation_failure",
                "const latent_declared_invocation_error *declared_error",
                "latent_retained_invocation_outcome",
                "latent_activation_status",
                "get_activation",
                "latent_cancel_response",
                "latent_error_detail",
                "const latent_error_detail *details",
                "latent_activation_success_summary",
            ),
        }
        for relative, tokens in expected.items():
            source = (ROOT / relative).read_text(encoding="utf-8")
            for token in tokens:
                self.assertIn(token, source, f"{relative}: {token}")

        rust = (ROOT / "sdk/rust/src/lib.rs").read_text(encoding="utf-8")
        self.assertNotIn(
            "pub struct CancelResponse {\n    pub disposition: CancelDisposition,",
            rust,
            "Rust cancellation must not duplicate the state carried by AlreadyTerminal",
        )
        core_error = (
            ROOT / "crates/latent-core/src/error.rs"
        ).read_text(encoding="utf-8")
        self.assertIn("pub details: Vec<ErrorDetail>", core_error)

        c = (ROOT / "sdk/c/include/latent/latent.h").read_text(encoding="utf-8")
        self.assertIn(
            "typedef struct latent_declared_invocation_error {\n"
            "    latent_invocation_receipt receipt;",
            c,
        )

    def test_execution_seam_has_a_first_class_declared_error_branch(self) -> None:
        executor = (
            ROOT / "crates/latent-executor/src/lib.rs"
        ).read_text(encoding="utf-8")
        runner = (
            ROOT / "crates/latent-node/src/activation_runner.rs"
        ).read_text(encoding="utf-8")
        backend = (
            ROOT / "crates/latent-wasmtime/src/backend.rs"
        ).read_text(encoding="utf-8")
        self.assertIn("DeclaredError {", executor)
        self.assertIn("GuestOutcome::DeclaredError", runner)
        self.assertIn(
            "ActivationOutcome::DeclaredError { error, consumption }", runner
        )
        self.assertIn("GuestOutcome::DeclaredError", backend)

    def test_documented_standalone_subset_marks_later_control_plane_calls_unimplemented(self) -> None:
        document = (
            ROOT / "docs/protocol/phase-1-contract-hardening.md"
        ).read_text(encoding="utf-8")
        for method in (
            "DeploymentService.WatchDeployment",
            "RouteService.WatchRouteSnapshots",
            "NodeService.RegisterNode",
            "NodeService.ReportInventory",
            "NodeService.Heartbeat",
        ):
            self.assertIn(method, document)
        self.assertIn("must never return an empty successful response", document)
        self.assertIn("phase1-descriptor-contract.json", document)
        self.assertIn("tools/validate_phase1_descriptor.py", document)


if __name__ == "__main__":
    unittest.main()
