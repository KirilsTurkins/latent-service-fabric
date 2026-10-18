"""Run the shipped operator tool outside a checkout with isolated Python imports."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tools import dev_tool_distribution as distribution


class ServerOperatorDistribution(unittest.TestCase):
    def setUp(self):
        owned = tempfile.TemporaryDirectory()
        self.addCleanup(owned.cleanup)
        self.root = Path(owned.name)
        self.payload = self.root / 'installed'
        self.payload.mkdir()
        distribution.recipe(self.payload, 'java')
        self.empty = self.root / 'outside-checkout'
        self.empty.mkdir()
        self.command = self.payload / 'recipe/tools/server_capsule.py'

    def run_tool(self, *arguments):
        environment = {**os.environ, 'PYTHONPATH': str(self.root / 'absent-pythonpath')}
        return subprocess.run([sys.executable, '-I', str(self.command), *map(str, arguments)],
            cwd=self.empty, env=environment, capture_output=True, timeout=30)

    def test_installed_recipe_has_complete_server_operator_import_closure(self):
        result = self.run_tool('--help')
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertIn(b'{plan,apply,remove,rollback,recover,inspect}', result.stdout)
        self.assertIn(b'--config', result.stdout)
        self.assertIn(b'--state', result.stdout)
        for name in ('server_capsule.py', 'server_routes.py', 'server_source.py'):
            self.assertEqual((self.payload / 'recipe/tools' / name).read_bytes(),
                             (distribution.ROOT / 'tools' / name).read_bytes())

    def test_installed_tool_rejects_invalid_declaration_before_operator_dispatch(self):
        from tools.tests.test_server_source import fixture
        from tools.dev_workflow.common import encode
        _files, profile, _plan, declaration, mounts, _pin = fixture()
        inputs = self.empty / 'inputs'
        inputs.mkdir()
        (inputs / 'client.json').write_bytes(b'{}')
        (inputs / 'component.wasm').write_bytes(b'actual-component-model-identity')
        (inputs / 'source-inputs.json').write_bytes(b'captured-source-model-identity')
        (inputs / 'profile.json').write_bytes(encode(profile))
        (inputs / 'mounts.json').write_bytes(encode(mounts))
        (inputs / 'declaration.json').write_bytes(encode(declaration))
        result = self.run_tool('--binary', sys.executable, '--config', inputs / 'client.json',
            '--state', self.empty / 'private-routes', '--tenant', 'examples', '--route', 'server',
            'plan', '--declaration', inputs / 'declaration.json', '--component', inputs / 'component.wasm',
            '--source-inputs', inputs / 'source-inputs.json', '--profile', inputs / 'profile.json',
            '--mounts', inputs / 'mounts.json')
        self.assertEqual(result.returncode, 2, result.stderr.decode())
        value = json.loads(result.stderr)
        self.assertEqual(value['error'], 'server-source-stale-componentDigest')
        self.assertTrue(value['outcomeKnown'])
        self.assertFalse(value['executionPermission'])
        self.assertFalse((self.empty / 'private-routes/server-routes.json').exists())

    def test_other_language_recipes_do_not_advertise_java_server_operator_tools(self):
        other = self.root / 'rust-tools'
        other.mkdir()
        distribution.recipe(other, 'rust')
        self.assertFalse((other / 'recipe/tools/server_capsule.py').exists())

    def test_installed_new_server_captures_the_exact_sdk_without_checkout_imports(self):
        from tools.java_capsule_project import validate, sdk_inputs
        from tools.rust_capsule_project import snapshot
        command = self.payload / 'recipe/tools/java_capsule.py'
        project = self.empty / 'independent-server'
        result = subprocess.run([sys.executable, '-I', str(command), 'new-server', str(project),
            '--name', 'independent-server'], cwd=self.empty, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        files = snapshot(project)
        selected, lock, _pins = validate(files)
        self.assertEqual(selected['server'], {'profile': 'lsf.java.httpserver.buffered.v1',
                                             'entryPoint': 'dev.latent.app.Server'})
        expected = sdk_inputs(distribution.ROOT)
        self.assertEqual({name.removeprefix('vendor/lsf/'): data for name, data in files.items()
                          if name.startswith('vendor/lsf/')}, expected)
        self.assertEqual(lock['template']['name'], 'httpserver')
        self.assertIn(b'HttpServer.create', files['src/dev/latent/app/Server.java'])
        self.assertNotIn('src/dev/latent/app/Capsule.java', files)
        observed = distribution.compiler_inventory(self.payload, '1' * 40, 'java')
        retained = {entry['path']: entry for entry in observed['files']}
        from tools.dev_workflow.common import digest
        for name, data in expected.items():
            entry = retained['recipe/' + name]
            self.assertEqual((entry['sha256'], entry['size']), (digest(data), len(data)))
        # A modified retained runtime cannot inherit the original project lock.
        runtime = 'vendor/lsf/sdk/java-guest/runtime/dev/latent/guest/Wire.java'
        self.assertIn(runtime, set(files))
        with self.assertRaisesRegex(ValueError, 'SDK'):
            validate({**files, runtime: files[runtime] + b'\n// changed captured runtime\n'})

    def test_installed_java_creator_preserves_every_existing_template(self):
        from tools.java_capsule_project import validate, AUTHORING_TEMPLATES
        from tools.rust_capsule_project import snapshot
        command = self.payload / 'recipe/tools/java_capsule.py'
        for template in AUTHORING_TEMPLATES:
            with self.subTest(template=template):
                project = self.empty / template
                result = subprocess.run([sys.executable, '-I', str(command), 'new', str(project),
                    '--template', template], cwd=self.empty, capture_output=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr.decode())
                _selected, lock, _pins = validate(snapshot(project))
                self.assertEqual(lock['template']['name'], template)


if __name__ == '__main__': unittest.main()
