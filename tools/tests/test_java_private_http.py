"""Real local-JAR capture controls; synthetic class headers are not execution."""
import copy
from pathlib import Path
import shutil
import struct
import tempfile
import unittest
from unittest.mock import Mock, patch

from tools import application_dependencies as inputs
from tools import java_dependency_resolution as resolver
from tools import qualify_java_private_http as gate
from tools.application_dependency_store import DependencyError
from tools.java_application_dependencies import classpath, selected_entries
from tools.rust_capsule_project import snapshot


class JavaPrivateHttpTests(unittest.TestCase):
    def test_explicit_source_compilation_never_runs_library_startup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            calls = []

            def compile_source(*arguments):
                calls.append(arguments)
                classes = root / 'classes/outside/http'
                classes.mkdir(parents=True)
                header = b'\xca\xfe\xba\xbe' + struct.pack('>HH', 0, 61) + b'not-executable-source-control'
                for name in ('Client', 'Child'):
                    (classes / (name + '.class')).write_bytes(header)

            jars = gate.make_jars(root, Mock(run=compile_source))
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][:6], ('private-http-javac', 'javac', '--release', '17', '-proc:none', '-encoding'))
            self.assertEqual(set(jars), {'primary', 'child'})
            self.assertEqual(selected_entries(jars['child'].read_bytes(), 25)['outside/http/badge.txt'], gate.RESOURCE)
            self.assertIn('url.openConnection(Proxy.NO_PROXY)', gate.LIBRARY)
            self.assertIn('url.openConnection()', gate.LIBRARY)
            self.assertIn('Child.beforeRequest()', gate.LIBRARY)
            self.assertNotIn('dev.latent', gate.LIBRARY + gate.CHILD)
            self.assertNotIn('ConnectionFactory', gate.LIBRARY)

    def test_both_actual_local_closures_survive_original_directory_removal_and_tamper_refusal(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            originals = root / 'outside'
            originals.mkdir()
            header = b'\xca\xfe\xba\xbe' + struct.pack('>HH', 0, 61) + b'not-executable-source-control'
            jars = {'primary': originals / 'primary.jar', 'child': originals / 'child.jar'}
            jars['primary'].write_bytes(gate.deterministic_jar({'outside/http/Client.class': header}))
            jars['child'].write_bytes(gate.deterministic_jar({'outside/http/Child.class': header,
                                                          'outside/http/badge.txt': gate.RESOURCE}))
            variants = []
            for ordinal, identities in enumerate(gate.IDENTITIES):
                owner = root / ('variant-' + str(ordinal))
                owner.mkdir()
                with patch.object(resolver, 'run_bounded_result', side_effect=AssertionError('local JAR executed a host resolver')):
                    app, receipt = gate.capture(owner, jars, identities)
                variants.append((owner, app, receipt))
            self.assertEqual(len({r['sdkLockDigest'] for _, _, r in variants}), 1)
            self.assertEqual(len({identity for _, _, r in variants for identity in r['identities']}), 4)
            accepted_before = snapshot(variants[0][1])
            rows = gate.negative_inputs(variants[0][1])
            self.assertEqual([row['case'] for row in rows], ['missing-transitive', 'tampered-transitive'])
            self.assertTrue(all(row['acceptedLockPreserved'] for row in rows))
            self.assertEqual(snapshot(variants[0][1]), accepted_before)
            shutil.rmtree(originals)
            for owner, app, receipt in variants:
                work, evidence = owner / 'offline', owner / 'evidence'
                work.mkdir()
                evidence.mkdir()
                with patch.object(inputs, 'fetch', side_effect=AssertionError('offline closure contacted registry')):
                    closure = inputs.prepare(app, work, evidence, 'java')
                    paths, selected = classpath(closure, owner / 'classpath')
                self.assertEqual(len(paths), 2)
                self.assertEqual({row['id'] for row in selected['artifacts']}, set(receipt['identities']))
                resource = next(row for row in selected['resources'] if row['path'] == 'outside/http/badge.txt')
                self.assertEqual(resource['owner'], receipt['identities'][1])
                self.assertEqual(resource['digest'], gate.digest(gate.RESOURCE))
                self.assertFalse(originals.exists())
                self.assertEqual(gate.digest((app / 'sdk-lock.json').read_bytes()), receipt['sdkLockDigest'])

    def test_unknown_or_duplicate_fixture_identity_refuses_before_project_creation(self):
        with patch.object(gate, 'standard_project') as create:
            for identities in (('arbitrary/1', 'arbitrary-child/1'), ('same/1', 'same/1')):
                with self.subTest(identities=identities), self.assertRaisesRegex(RuntimeError, 'fixture-identity'):
                    gate.capture(Path('unused'), {}, identities)
            create.assert_not_called()

    def test_forged_case_list_or_nonretired_or_replayed_provider_record_refuses(self):
        original = {'status': 'passed', 'cases': list(gate.EXPECTED_CASES),
            'shutdown': {'reaped': True, 'record': {'clean': True}}, 'peerReaped': True,
            'peer': {'startedRequests': 11, 'rejectedRequests': 0, 'committedMutations': 1,
                     'requests': [{'role': 'primary'} for _ in range(11)]}}
        gate.verify_node(original)
        for kind in ('different-case', 'missing-case', 'unclean', 'unreaped', 'bool-as-int', 'bool-count', 'replay', 'alternate'):
            row = copy.deepcopy(original)
            if kind == 'different-case': row['cases'][-1] = 'invented'
            elif kind == 'missing-case': row['cases'].pop()
            elif kind == 'unclean': row['shutdown']['record']['clean'] = False
            elif kind == 'unreaped': row['peerReaped'] = False
            elif kind == 'bool-as-int': row['shutdown']['reaped'] = 1
            elif kind == 'bool-count': row['peer']['committedMutations'] = True
            elif kind == 'replay': row['peer']['committedMutations'] = 2
            else: row['peer']['requests'][0]['role'] = 'secondary'
            with self.subTest(kind=kind), self.assertRaisesRegex(RuntimeError, 'signed-provider-incomplete'):
                gate.verify_node(row)

    def test_nonlinux_refusal_precedes_directory_or_tool_access(self):
        with patch.object(gate.sys, 'platform', 'win32'), patch.object(gate, 'fresh') as fresh:
            with self.assertRaisesRegex(RuntimeError, 'linux-required'):
                gate.qualify(Path('unused'), Path('unused'), Path('unused'), Path('unused'), Path('unused'))
            fresh.assert_not_called()


if __name__ == '__main__':
    unittest.main()
