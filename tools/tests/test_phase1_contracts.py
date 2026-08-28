"""Regression tests for Issue #36's cross-layer Phase 1 contract changes."""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[2]
PROTO_ROOT = ROOT / "api" / "proto"


def declaration_body(source: str, declaration: str, name: str) -> str:
    match = re.search(
        rf"\b{re.escape(declaration)}\s+{re.escape(name)}\s*\{{", source
    )
    if match is None:
        raise AssertionError(f"missing {declaration} {name}")

    opening = source.index("{", match.start())
    depth = 0
    for index in range(opening, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[opening + 1 : index]
    raise AssertionError(f"unterminated {declaration} {name}")


def proto_fields(message: str) -> dict[str, int]:
    expression = re.compile(
        r"(?:^|\n)\s*(?:optional\s+|repeated\s+)?"
        r"(?:map\s*<[^>]+>|[A-Za-z_][A-Za-z0-9_.]*)\s+"
        r"([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(\d+)\s*;"
    )
    return {name: int(number) for name, number in expression.findall(message)}


class ProtoFieldContractTests(unittest.TestCase):
    def test_checked_in_field_contract_matches_authoritative_protobuf(self) -> None:
        contract = json.loads(
            (PROTO_ROOT / "phase1-field-contract.json").read_text(encoding="utf-8")
        )

        for expectation in contract["messages"]:
            source = (PROTO_ROOT / expectation["file"]).read_text(encoding="utf-8")
            body = declaration_body(source, "message", expectation["name"])
            fields = proto_fields(body)

            for number in expectation["reservedNumbers"]:
                self.assertRegex(body, rf"\breserved\s+{number}\s*;")
            for field_name in expectation["reservedNames"]:
                self.assertIn(f'"{field_name}"', body)
            for field_name, number in expectation["fields"].items():
                self.assertEqual(fields.get(field_name), number)

    def test_error_details_and_terminal_outcomes_are_not_flattened(self) -> None:
        invocation = (
            PROTO_ROOT / "latent/invocation/v1/invocation.proto"
        ).read_text(encoding="utf-8")
        common = (
            PROTO_ROOT / "latent/control/v1/common.proto"
        ).read_text(encoding="utf-8")

        for source in (invocation, common):
            self.assertIn("message ErrorDetail", source)
            self.assertIn("repeated ErrorDetail detail_items = 5;", source)
            self.assertNotIn("map<string, string> details = 4;", source)

        self.assertIn("DeclaredError declared_error = 8;", invocation)
        self.assertIn("PlatformError platform_failure = 9;", invocation)
        self.assertIn("BudgetConsumption final_consumption = 9;", invocation)
        self.assertIn("CANCEL_DISPOSITION_ALREADY_TERMINAL", invocation)


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
            self.assertEqual(list(self.schema_validator(schema_name).iter_errors(document)), [])

        route = json.loads((ROOT / "examples/route-snapshot.json").read_text(encoding="utf-8"))
        self.assertEqual(route["services"][0]["tenant"], "examples")
        self.assertEqual(route["bindings"][0]["consumerTenant"], "examples")
        self.assertEqual(route["bindings"][0]["providerTenant"], "examples")

    def test_wit_and_all_sdk_surfaces_use_the_relative_budget_and_typed_errors(self) -> None:
        context = (ROOT / "wit/platform/context/package.wit").read_text(encoding="utf-8")
        invoke = (ROOT / "wit/platform/invocation/package.wit").read_text(encoding="utf-8")
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

    def test_documented_standalone_subset_marks_later_control_plane_calls_unimplemented(self) -> None:
        document = (ROOT / "docs/protocol/phase-1-contract-hardening.md").read_text(
            encoding="utf-8"
        )
        for method in (
            "DeploymentService.WatchDeployment",
            "RouteService.WatchRouteSnapshots",
            "NodeService.RegisterNode",
            "NodeService.ReportInventory",
            "NodeService.Heartbeat",
        ):
            self.assertIn(method, document)
        self.assertIn("must never return an empty successful response", document)


if __name__ == "__main__":
    unittest.main()
