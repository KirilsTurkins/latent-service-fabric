from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from tools.java_guest.model import Graph
from tools.java_guest import java, c, async_imports
from tools.java_guest.surface import surface


def document():
    return {"worlds": [{"name": "service", "imports": {}, "exports": {"interface-0": {"interface": {"id": 0}}}, "package": 0}],
            "interfaces": [{"name": "api", "package": 0, "types": {}, "functions": {"run": {
                "name": "run", "kind": "freestanding", "params": [{"name": "value", "type": "u64"}], "result": 0}}}],
            "types": [{"name": None, "kind": {"result": {"ok": "s64", "err": "string"}}, "owner": None}],
            "packages": [{"name": "examples:sample@1.0.0", "interfaces": {"api": 0}, "worlds": {"service": 0}}]}


HEADER = "void exports_examples_sample_api_run(uint64_t value, sample_result_t *ret);\n"


class Bindings(unittest.TestCase):
    @staticmethod
    def asynchronous_document():
        data = document()
        data['interfaces'].append({'name': 'pending', 'package': 0, 'types': {}, 'functions': {
            'wait': {'name': 'wait', 'kind': 'async-freestanding', 'params': [{'name': 'value', 'type': 'u32'}],
                     'result': 'u32'}}})
        data['worlds'][0]['imports'] = {'interface-1': {'interface': {'id': 1}}}
        header = HEADER + 'extern probe_subtask_status_t examples_sample_pending_wait(uint32_t value, uint32_t *result);\n'
        return data, header

    def test_async_import_abi_requires_explicit_profile_and_real_async_wit(self):
        data, header = self.asynchronous_document()
        with self.assertRaisesRegex(ValueError, 'outside the selected Java profile'):
            Graph(data, 'service', header)
        with self.assertRaisesRegex(ValueError, 'explicit boolean'):
            Graph(data, 'service', header, async_imports=1)
        data['interfaces'][1]['functions']['wait']['kind'] = 'freestanding'
        with self.assertRaisesRegex(ValueError, 'outside the selected Java profile'):
            Graph(data, 'service', header, async_imports=True)

    def test_async_result_area_cannot_be_missing_flattened_or_used_by_sync_bridge(self):
        data, header = self.asynchronous_document()
        for invalid in (header.replace(', uint32_t *result', ''), header.replace('*result', 'result')):
            with self.subTest(header=invalid), self.assertRaises(ValueError):
                Graph(data, 'service', invalid, async_imports=True)
        graph = Graph(data, 'service', header, async_imports=True)
        self.assertTrue(graph.imports[0]['asyncLowered'])
        with self.assertRaisesRegex(ValueError, 'owned pending-call bridge'):
            c.generate(graph)

    def test_true_async_c_export_is_rejected_even_with_import_profile_selected(self):
        with self.assertRaisesRegex(ValueError, 'asynchronous C exports'):
            Graph(document(), 'service', HEADER.replace('void ', 'probe_callback_code_t ', 1), async_imports=True)

    def test_internal_wait_cancellation_rejects_resource_results_through_aliases(self):
        data, header = self.asynchronous_document()
        data['packages'].append({'name': 'latent:runtime@0.1.0', 'interfaces': {'activation': 1}, 'worlds': {}})
        data['interfaces'][1].update(name='activation', package=1)
        function = data['interfaces'][1]['functions'].pop('wait')
        function['name'] = 'timer-next'
        data['interfaces'][1]['functions']['timer-next'] = function
        header = header.replace('examples_sample_pending_wait', 'latent_runtime_activation_timer_next')
        graph = Graph(data, 'service', header, async_imports=True)
        async_imports.generate(graph)
        resource = len(data['types'])
        data['types'].extend([
            {'name': 'handle', 'kind': 'resource', 'owner': {'interface': 1}},
            {'name': None, 'kind': {'handle': {'own': resource}}, 'owner': None},
            {'name': None, 'kind': {'option': resource + 1}, 'owner': None},
        ])
        function['result'] = resource + 2
        graph = Graph(data, 'service', header, async_imports=True)
        with self.assertRaisesRegex(ValueError, 'cannot transfer resources'):
            async_imports.generate(graph)

    def test_reused_shallow_types_cannot_hide_an_excessive_graph_depth(self):
        data = document()
        data["types"] = [{"name": None, "owner": None, "kind": {"list": index + 1 if index < 34 else "string"}}
                         for index in range(35)]
        data["interfaces"][0]["functions"] = {
            "shallow": {"name": "shallow", "kind": "freestanding", "params": [], "result": 31},
            "deep": {"name": "deep", "kind": "freestanding", "params": [], "result": 0},
        }
        with self.assertRaisesRegex(ValueError, "excessively nested"):
            Graph.preflight(data, "service")

    def test_c_bridge_expansion_of_a_shared_type_graph_is_bounded(self):
        data = document()
        data["types"] = [{"name": None, "owner": None, "kind": {"record": {"fields": [
            {"name": "left", "type": index + 1 if index < 16 else "string"},
            {"name": "right", "type": index + 1 if index < 16 else "string"}]}}} for index in range(17)]
        graph = Graph(data, "service", HEADER)
        with self.assertRaisesRegex(ValueError, "C bridge traversal"):
            c.generate(graph)

    def test_documented_interface_reference_preserves_semantics_and_validates_identity(self):
        original = document()
        expected = java.generate(Graph(original, "service", HEADER))
        annotated = deepcopy(original)
        reference = annotated["worlds"][0]["exports"]["interface-0"]["interface"]
        reference["docs"] = {"contents": "Authoritative principal, trace and deadline are host context."}
        self.assertEqual(java.generate(Graph(annotated, "service", HEADER)), expected)
        for field, value in (("id", True), ("id", 999), ("docs", {"contents": 7}), ("authority", "public")):
            changed = deepcopy(annotated)
            changed["worlds"][0]["exports"]["interface-0"]["interface"][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError): Graph(changed, "service", HEADER)

    def test_shared_imported_resource_alias_uses_one_owner_class(self):
        data = document()
        data["interfaces"].extend([
            {"name": "state", "package": 0, "types": {"transaction": 1}, "functions": {
                "acquire": {"name": "acquire", "kind": "freestanding", "params": [], "result": 3}}},
            {"name": "intents", "package": 0, "types": {"transaction": 2}, "functions": {
                "stage": {"name": "stage", "kind": "async-freestanding", "params": [{"name": "transaction", "type": 4}], "result": None}}},
        ])
        data["worlds"][0]["imports"] = {"interface-1": {"interface": {"id": 1}}, "interface-2": {"interface": {"id": 2}}}
        data["types"].extend([
            {"name": "transaction", "kind": "resource", "owner": {"interface": 1}},
            {"name": "transaction", "kind": {"type": 1}, "owner": {"interface": 2}},
            {"name": None, "kind": {"handle": {"own": 2}}, "owner": None},
            {"name": None, "kind": {"handle": {"borrow": 2}}, "owner": None},
        ])
        header = HEADER + "sample_own_transaction_t examples_sample_state_acquire(void);\nvoid examples_sample_intents_stage(sample_borrow_transaction_t transaction);\n"
        graph = Graph(data, "service", header)
        output = java.generate(graph)
        self.assertEqual(graph.resources, [1])
        self.assertIn("stage(ExamplesSampleStateTransaction arg0)", output)
        self.assertIn("return new ExamplesSampleStateTransaction((int) input.integer(4));", output)
        self.assertNotIn("ExamplesSampleIntentsTransaction", output)
        self.assertNotIn("writeT2(", output)
        self.assertNotIn("readT2(", output)
        graph.types[2]["kind"] = {"type": 2}
        with self.assertRaisesRegex(ValueError, "recursive Java resource alias"):
            graph.resource_index(2)

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
