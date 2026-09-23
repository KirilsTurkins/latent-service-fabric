from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from tools.java_guest.model import Graph
from tools.java_guest import java, c
from tools.java_guest.surface import surface


def document():
    return {"worlds": [{"name": "service", "imports": {}, "exports": {"interface-0": {"interface": {"id": 0}}}, "package": 0}],
            "interfaces": [{"name": "api", "package": 0, "types": {}, "functions": {"run": {
                "name": "run", "kind": "freestanding", "params": [{"name": "value", "type": "u64"}], "result": 0}}}],
            "types": [{"name": None, "kind": {"result": {"ok": "s64", "err": "string"}}, "owner": None}],
            "packages": [{"name": "examples:sample@1.0.0", "interfaces": {"api": 0}, "worlds": {"service": 0}}]}


HEADER = "void exports_examples_sample_api_run(uint64_t value, sample_result_t *ret);\n"


class Bindings(unittest.TestCase):
    def test_surface_preserves_async_width_identity_and_ignores_parser_ids(self):
        original = document()
        expected = surface(original, "service")
        moved = deepcopy(original)
        moved["types"].insert(0, {"name": None, "kind": {"type": "u8"}, "owner": None})
        moved["interfaces"][0]["functions"]["run"]["result"] = 1
        self.assertEqual(surface(moved, "service"), expected)
        for field, changed in (("kind", "async-freestanding"), ("result", "s32")):
            data = deepcopy(original)
            data["interfaces"][0]["functions"]["run"][field] = changed
            self.assertNotEqual(surface(data, "service"), expected)
        data = deepcopy(original)
        data["packages"][0]["name"] = "examples:sample@2.0.0"
        self.assertNotEqual(surface(data, "service"), expected)

    def test_borrowed_export_parameters_are_rejected_before_compilation(self):
        data = document()
        data["types"].extend([
            {"name": "item", "kind": "resource", "owner": {"interface": 0}},
            {"name": None, "kind": {"handle": {"borrow": 1}}, "owner": None}])
        data["interfaces"][0]["functions"]["run"]["params"][0]["type"] = 2
        with self.assertRaisesRegex(ValueError, "borrowed resource export"):
            Graph(data, "service", HEADER)

    def test_full_width_result_and_source_owned_exports_are_explicit(self):
        graph = Graph(document(), "examples:sample/service@1.0.0", HEADER)
        output = java.generate(graph)
        self.assertIn("Result<Long, String> run(Unsigned64 arg0)", output)
        self.assertIn("new dev.latent.app.Capsule().run(arg0)", output)
        self.assertIn("value.bits(), 8", output)
        self.assertNotIn("catch (", output)
        self.assertEqual(output, java.generate(graph))
        bridge = c.generate(graph)
        self.assertIn("lsf_java_free(owned)", bridge)
        self.assertIn("lsf_allocate", bridge)
        self.assertNotIn("double", bridge)

    def test_imported_resources_cannot_escape_through_public_rpc_values(self):
        for ownership in ("own", "borrow"):
            for selected in (1, 2, 3):
                for position in ("parameter", "result"):
                    with self.subTest(ownership=ownership, selected=selected, position=position):
                        data = document()
                        data["interfaces"].append({"name": "resources", "package": 0,
                                                   "types": {"item": 1}, "functions": {}})
                        data["worlds"][0]["imports"]["interface-1"] = {"interface": {"id": 1}}
                        data["types"].extend([
                            {"name": "item", "kind": "resource", "owner": {"interface": 1}},
                            {"name": None, "kind": {"handle": {ownership: 1}}, "owner": None},
                            {"name": None, "kind": {"option": 2}, "owner": None}])
                        function = data["interfaces"][0]["functions"]["run"]
                        if position == "parameter": function["params"][0]["type"] = selected
                        else: function["result"] = selected
                        with self.assertRaisesRegex(ValueError, "exported resources|resource export values"):
                            Graph(data, "service", HEADER)

    def test_parameter_names_cannot_shadow_private_transport_locals(self):
        for name in ("input", "output", "result", "operation", "arguments", "data", "length"):
            data = document()
            data["interfaces"][0]["functions"]["run"]["params"][0]["name"] = name
            header = HEADER.replace("uint64_t value", "uint64_t " + name)
            graph = Graph(data, "service", header)
            self.assertIn("Unsigned64 arg0", java.generate(graph))
            self.assertIn("uint64_t arg0, sample_result_t *arg1", c.generate(graph))

    def test_unsupported_future_and_inline_interface_fail_closed(self):
        data = document()
        data["types"][0]["kind"] = {"future": "u64"}
        with self.assertRaisesRegex(ValueError, "unsupported Java WIT type"):
            Graph(data, "service", HEADER)
        data = document()
        data["worlds"][0]["imports"]["function"] = {"function": {}}
        with self.assertRaisesRegex(ValueError, "named interface"):
            Graph(data, "service", HEADER)

    def test_empty_records_fail_before_java_compilation(self):
        data = document()
        data["types"][0]["kind"] = {"record": {"fields": []}}
        with self.assertRaisesRegex(ValueError, "component records require a field"):
            Graph(data, "service", HEADER)

    def test_exported_resources_and_resource_methods_fail_closed(self):
        data = document()
        data["types"][0] = {"name": "item", "kind": "resource", "owner": {"interface": 0}}
        with self.assertRaisesRegex(ValueError, "exported resources"):
            Graph(data, "service", HEADER)
        data = document()
        data["interfaces"][0]["functions"]["run"]["kind"] = {"method": 0}
        with self.assertRaisesRegex(ValueError, "resource constructors"):
            Graph(data, "service", HEADER)

    def test_current_generator_signature_must_match_unflattened_types(self):
        with self.assertRaisesRegex(ValueError, "signature not found"):
            Graph(document(), "service", "")
        with self.assertRaisesRegex(ValueError, "unexpected flattened"):
            Graph(document(), "service", "void exports_examples_sample_api_run(uint64_t value);\n")
        with self.assertRaisesRegex(ValueError, "resolve exactly once"):
            Graph(document(), "unselected", HEADER)


if __name__ == "__main__": unittest.main()
