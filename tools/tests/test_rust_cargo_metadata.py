"""Native metadata admission controls; no Cargo/compiler/component execution."""
import copy
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from tools import rust_application_dependencies as native
from tools.application_dependencies import LOCK
from tools.application_dependency_store import DependencyError
from tools.build_snapshot import canonical
from tools.tests import test_rust_dependency_authoring as fixture


class CargoMetadata(unittest.TestCase):
    def setUp(self):
        self.root = Path('observed-project').resolve()
        packages = [{'id': name, 'manifest_path': str(self.root / name / 'Cargo.toml'),
                     'future-package': {'retained': True}} for name in ('root', 'shared', 'other-target')]
        packages[0]['manifest_path'] = str(self.root / 'Cargo.toml')
        kinds = [{'kind': None, 'target': None}, {'kind': 'build', 'target': 'cfg(windows)'}]
        edges = [{'name': 'renamed', 'pkg': 'shared', 'dep_kinds': kinds, 'future-edge': 4},
                 {'name': 'other_alias', 'pkg': 'shared', 'dep_kinds': [{'kind': 'dev', 'target': None}]},
                 {'name': 'other_target', 'pkg': 'other-target', 'dep_kinds': [{'kind': None, 'target': 'cfg(windows)'}]}]
        nodes = [{'id': 'root', 'deps': edges, 'dependencies': ['shared', 'other-target'],
                  'features': ['default', 'optional'], 'future-node': 'full'},
                 {'id': 'shared', 'deps': [], 'dependencies': [], 'features': ['alloc']},
                 {'id': 'other-target', 'deps': [], 'features': []}]
        self.full = {'version': 1, 'packages': packages, 'resolve': {'root': 'root', 'nodes': nodes}, 'future': True}
        self.selected = copy.deepcopy(self.full)
        selected_nodes = self.selected['resolve']['nodes']
        selected_nodes.pop()
        selected_nodes[0]['deps'].pop()
        selected_nodes[0]['deps'][0]['dep_kinds'].pop()
        selected_nodes[0].update(features=['optional'], dependencies=['shared'], **{'future-node': 'filtered'})

    def test_filtered_features_aliases_edge_kinds_and_unknown_fields_remain_exact(self):
        before = canonical([self.full, self.selected])
        result = native.selected_graph(self.full, self.selected, self.root)
        self.assertIs(result, self.selected['resolve'])
        self.assertEqual(canonical([self.full, self.selected]), before)
        self.assertEqual(result['nodes'][0]['features'], ['optional'])
        self.assertEqual([row['name'] for row in result['nodes'][0]['deps']], ['renamed', 'other_alias'])
        self.assertEqual(result['nodes'][0]['deps'][0]['dep_kinds'], [{'kind': None, 'target': None}])
        self.assertEqual(result['nodes'][0]['future-node'], 'filtered')

    def test_native_filter_may_omit_target_only_packages_without_rewriting_shared_records(self):
        self.selected['packages'].pop()
        self.assertIs(native.selected_graph(self.full, self.selected, self.root), self.selected['resolve'])
        self.assertEqual(len(self.full['packages']), 3)
        self.assertEqual(len(self.selected['packages']), 2)
        self.selected['packages'].append({'id': 'foreign', 'manifest_path': 'outside/Cargo.toml'})
        with self.assertRaisesRegex(DependencyError, '^cargo-selected-graph-package-drift$'):
            native.selected_graph(self.full, self.selected, self.root)

    def test_duplicate_package_and_node_ids_are_not_silently_collapsed(self):
        for side in ('full', 'selected'):
            for field in ('packages', 'nodes'):
                with self.subTest(side=side, field=field):
                    value = copy.deepcopy(getattr(self, side))
                    rows = value['packages'] if field == 'packages' else value['resolve']['nodes']
                    rows.append(copy.deepcopy(rows[0]))
                    arguments = (value, self.selected) if side == 'full' else (self.full, value)
                    with self.assertRaisesRegex(DependencyError, '^cargo-native-graph-duplicate-id$'):
                        native.selected_graph(*arguments, self.root)

    def test_malformed_fields_fail_with_closed_errors_instead_of_python_type_errors(self):
        mutations = [lambda m: m.update(version=True), lambda m: m.update(packages={}),
                     lambda m: m['resolve'].update(root=[]), lambda m: m['resolve'].update(nodes=[None]),
                     lambda m: m['resolve']['nodes'][0].update(features=['same', 'same']),
                     lambda m: m['resolve']['nodes'][0].update(features=[{}]),
                     lambda m: m['resolve']['nodes'][0]['deps'][0].update(pkg=[]),
                     lambda m: m['resolve']['nodes'][0]['deps'][0].update(name=None),
                     lambda m: m['resolve']['nodes'][0]['deps'][0].update(dep_kinds=[{'kind': 'ambient', 'target': None}]),
                     lambda m: m['resolve']['nodes'][0]['deps'][0].update(dep_kinds=[{'kind': None}]),
                     lambda m: m['resolve']['nodes'][0]['deps'][0].update(dep_kinds=[{'kind': None, 'target': {}}])]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                value = copy.deepcopy(self.full); mutate(value)
                with self.assertRaisesRegex(DependencyError, '^cargo-native-(graph|edge)'):
                    native.selected_graph(value, self.selected, self.root)

    def test_full_and_filtered_graphs_require_closed_edges_and_consistent_dependency_ids(self):
        for side in ('full', 'selected'):
            for field in ('pkg', 'dependencies'):
                with self.subTest(side=side, field=field):
                    value = copy.deepcopy(getattr(self, side))
                    if field == 'pkg': value['resolve']['nodes'][0]['deps'][0]['pkg'] = 'foreign'
                    else: value['resolve']['nodes'][0]['dependencies'] = []
                    arguments = (value, self.selected) if side == 'full' else (self.full, value)
                    with self.assertRaisesRegex(DependencyError, '^cargo-native-edge-not-closed$'):
                        native.selected_graph(*arguments, self.root)

    def test_native_root_is_shared_and_bound_to_the_actual_application_manifest(self):
        for side in ('full', 'selected'):
            value = copy.deepcopy(getattr(self, side)); value['resolve']['root'] = 'shared'
            arguments = (value, self.selected) if side == 'full' else (self.full, value)
            with self.subTest(side=side), self.assertRaisesRegex(DependencyError, '^cargo-native-graph-root-invalid$'):
                native.selected_graph(*arguments, self.root)
        with self.assertRaisesRegex(DependencyError, '^cargo-native-graph-root-invalid$'):
            native.selected_graph(self.full, self.selected, self.root / 'different')

    def test_filtered_package_feature_and_edge_observations_cannot_appear_from_nowhere(self):
        mutations = [lambda m: m['packages'][1].update(**{'future-package': 'changed'}),
                     lambda m: m['resolve']['nodes'][0]['features'].append('foreign-feature'),
                     lambda m: m['resolve']['nodes'][0]['deps'][0].update(name='foreign-alias'),
                     lambda m: m['resolve']['nodes'][0]['deps'][0]['dep_kinds'].append({'kind': 'build', 'target': None})]
        for index, mutate in enumerate(mutations):
            value = copy.deepcopy(self.selected); mutate(value)
            with self.subTest(index=index), self.assertRaisesRegex(DependencyError, '^cargo-selected-graph-.*-drift$'):
                native.selected_graph(self.full, value, self.root)

    def test_duplicate_edges_and_kind_observations_are_refused(self):
        for field in ('deps', 'dep_kinds'):
            value = copy.deepcopy(self.full)
            rows = value['resolve']['nodes'][0]['deps']
            if field == 'dep_kinds': rows = rows[0]['dep_kinds']
            rows.append(copy.deepcopy(rows[0]))
            with self.subTest(field=field), self.assertRaisesRegex(DependencyError, '^cargo-native-edge-(kind-)?duplicate$'):
                native.selected_graph(value, self.selected, self.root)

    def test_feature_vectors_keep_native_capacity_and_the_original_aggregate_bound(self):
        value = copy.deepcopy(self.full)
        value['packages'] = value['packages'][:1]
        value['resolve']['nodes'] = [{'id': 'root', 'features': [f'feature-{i}' for i in range(65536)], 'deps': []}]
        self.assertIs(native.native_graph(value)[1]['root'], value['resolve']['nodes'][0])
        value['resolve']['nodes'][0]['features'].append('one-too-many')
        with self.assertRaisesRegex(DependencyError, '^cargo-native-graph-invalid$'):
            native.native_graph(value)
        value = copy.deepcopy(self.full)
        value['resolve']['nodes'][0]['features'] = [f'root-{i}' for i in range(32768)]
        value['resolve']['nodes'][1]['features'] = [f'shared-{i}' for i in range(32768)]
        with self.assertRaisesRegex(DependencyError, '^cargo-native-metadata-limit$'):
            native.native_graph(value)

    def test_feature_capacity_does_not_expand_packages_edges_dependency_ids_or_kinds(self):
        mutations = [lambda m: m.update(packages=m['packages']*342),
                     lambda m: m['resolve'].update(nodes=m['resolve']['nodes']*342),
                     lambda m: m['resolve']['nodes'][0].update(deps=[{'pkg': 'shared'}]*1025),
                     lambda m: m['resolve']['nodes'][0].update(dependencies=[f'id-{i}' for i in range(1025)]),
                     lambda m: m['resolve']['nodes'][0]['deps'][0].update(dep_kinds=[{'kind': None, 'target': None}]*1025)]
        for index, mutate in enumerate(mutations):
            value = copy.deepcopy(self.full); mutate(value)
            with self.subTest(index=index), self.assertRaisesRegex(DependencyError, '^cargo-native-graph-invalid$'):
                native.native_graph(value)

    def test_json_duplicate_fields_invalid_constants_and_finite_limits_fail_closed(self):
        with self.assertRaisesRegex(DependencyError, '^cargo-native-metadata-duplicate-field$'):
            native.native_metadata(b'{"version":1,"version":1}')
        for raw in (b'{', b'\xff', b'{"unknown":NaN}'):
            with self.subTest(raw=raw), self.assertRaisesRegex(DependencyError, '^cargo-native-metadata-invalid$'):
                native.native_metadata(raw)
        with patch.object(native, 'MAX_METADATA_BYTES', 3), self.assertRaisesRegex(DependencyError, '^cargo-native-metadata-limit$'):
            native.native_metadata(b'null')
        with patch.object(native, 'MAX_GRAPH_ROWS', 2), self.assertRaisesRegex(DependencyError, '^cargo-native-metadata-limit$'):
            native.selected_graph(self.full, self.selected, self.root)


class CargoMetadataCapture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.RustDependencyAuthoring.setUpClass.__func__(cls)

    setUp = fixture.RustDependencyAuthoring.setUp
    select = fixture.RustDependencyAuthoring.select
    metadata = fixture.RustDependencyAuthoring.metadata
    capture = fixture.RustDependencyAuthoring.capture

    def resolver_command(self, command, cwd, environment, seconds, maximum):
        result = fixture.RustDependencyAuthoring.resolver_command(self, command, cwd, environment, seconds, maximum)
        if command[1] == 'metadata' and ('--filter-platform' in command) == self.filtered:
            value = json.loads(result.stdout)
            self.mutate(value)
            return subprocess.CompletedProcess(command, 0, canonical(value), b'')
        return result

    def test_invalid_filtered_observation_cannot_publish_or_start_vendor(self):
        self.filtered = True
        mutations = [lambda m: m['resolve'].update(root='outside'),
                     lambda m: m['resolve']['nodes'][0]['features'].append('uncaptured'),
                     lambda m: m['resolve']['nodes'].append(copy.deepcopy(m['resolve']['nodes'][0])),
                     lambda m: m['packages'][0].update(version='9.9.9')]
        accepted = self.app / LOCK
        accepted.write_bytes(b'previous accepted bytes')
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                self.calls = []; self.mutate = mutate
                with self.assertRaisesRegex(DependencyError, '^cargo-(native|selected)-graph-'):
                    self.capture()
                self.assertEqual(accepted.read_bytes(), b'previous accepted bytes')
                self.assertFalse(any(command[1] == 'vendor' for command, *_ in self.calls))
                self.assertFalse(list(self.root.glob('candidate-*.json')))

    def test_duplicate_full_native_package_cannot_be_collapsed_before_capture(self):
        self.filtered = False
        self.mutate = lambda m: m['packages'].append(copy.deepcopy(m['packages'][0]))
        with self.assertRaisesRegex(DependencyError, '^cargo-native-graph-duplicate-id$'):
            self.capture()
        self.assertFalse(any(command[1] == 'vendor' for command, *_ in self.calls))
        self.assertFalse(list(self.root.glob('candidate-*.json')))


if __name__ == '__main__':
    unittest.main()
