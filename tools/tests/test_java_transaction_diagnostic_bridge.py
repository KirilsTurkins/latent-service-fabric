"""Strict source-routing oracles; no native signing or guest execution occurs."""
from dataclasses import replace
from pathlib import Path
import unittest

from tools.java_transaction_qualification import packaging
from tools.java_transaction_qualification.inputs import ComponentInput, COMPONENT_DIGESTS, COMPILER_SOURCE


def items():
    result = []
    for name in ("aggregate", "put-once-legacy-v1", "put-once-compatible-v2", "put-once-writer-v2"):
        result.append(ComponentInput(name, Path("fixture") / name, COMPONENT_DIGESTS[name],
            "sha256:" + "a" * 64, "sha256:" + "b" * 64, COMPILER_SOURCE,
            "sha256:" + "c" * 64, "sha256:" + "d" * 64))
    diagnostic = replace(result[1], name="put-once-diagnostics", compiler_source="e" * 40,
                         component_digest="sha256:" + "f" * 64)
    return tuple(result) + (diagnostic,)


class DiagnosticBridgeTests(unittest.TestCase):
    def test_diagnostic_uses_explicit_independent_source_and_exact_four_originals(self):
        selected = items()
        mode, arguments, record = packaging.signing_plan(selected, Path("output"), None)
        self.assertEqual(mode, "fixture-sign-java-diagnostic-inputs")
        self.assertEqual(arguments[:2], ["e" * 40, Path("output/put-once-diagnostics")])
        self.assertEqual(len(arguments), 6)
        self.assertEqual(record["originalCompilerSource"], COMPILER_SOURCE)
        self.assertIs(record["signedExecutionQualified"], False)
        self.assertIs(record["compilerExecutedAgain"], False)

    def test_original_current_six_and_value_routes_never_enter_diagnostic_bridge(self):
        selected = items()
        self.assertEqual(packaging.signing_plan(selected[:-1], Path("output"), None)[0], "fixture-sign-java-inputs")
        self.assertEqual(packaging.signing_plan(selected, Path("output"), "e" * 40)[0],
                         "fixture-sign-current-java-inputs")
        value = replace(selected[-1], name="put-once-values")
        self.assertEqual(packaging.signing_plan((value,), Path("output"), "e" * 40)[0],
                         "fixture-sign-current-java-inputs")

    def test_swapped_source_name_component_or_original_links_refuse_without_fallback(self):
        selected = items()
        altered = [selected[1:], selected + (selected[0],),
            (replace(selected[0], compiler_source="e" * 40),) + selected[1:],
            (replace(selected[0], component_digest="sha256:" + "0" * 64),) + selected[1:],
            (replace(selected[0], name="put-once-values"),) + selected[1:]]
        for field, replacement in (("compiler_source", COMPILER_SOURCE), ("companion_digest", "changed"),
                                   ("requirements_digest", "changed"), ("host_abi_digest", "changed")):
            altered.append(selected[:-1] + (replace(selected[-1], **{field: replacement}),))
        for candidate in altered:
            with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                packaging.signing_plan(candidate, Path("output"), None)
