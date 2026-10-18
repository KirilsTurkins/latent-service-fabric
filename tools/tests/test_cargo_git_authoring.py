"""Explicit Git authoring controls; native Cargo outputs are modelled."""
import json
import re
import subprocess
import tomllib
import unittest
from unittest.mock import patch

from tools import cargo_native_authoring as authoring, rust_capsule
from tools.application_dependency_store import DependencyError
from tools.build_snapshot import canonical
from tools.tests import test_cargo_native_authoring as fixture


class CargoGitAuthoring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.CargoNativeAuthoring.setUpClass.__func__(cls)

    select = fixture.CargoNativeAuthoring.select
    author = fixture.CargoNativeAuthoring.author

    def setUp(self):
        fixture.CargoNativeAuthoring.setUp(self)
        self.url, self.rev = 'https://example.test/developer/ordinary.git', 'a' * 40
        self.native_version = '1.0.0'
        self.declaration = {}
        self.alter_metadata = lambda value: None
        self.alter_lock = lambda value: None

    def command(self, command, cwd, environment, seconds, maximum):
        if command[1] == 'add' and '--git' in command:
            self.commands.append((list(command), cwd, dict(environment)))
            self.assertEqual(command[2], 'outside')
            self.assertEqual(command[command.index('--git') + 1], self.url)
            self.assertEqual(command[command.index('--rev') + 1], self.rev)
            self.assertEqual(seconds, 600)
            self.assertEqual(maximum, 4 * 1024 * 1024)
            path = command[command.index('--manifest-path') + 1]
            from pathlib import Path
            path = Path(path)
            value = {'git': self.url, 'rev': self.rev, **self.declaration}
            text = re.sub(r'^outside\s*=.*(?:\n|$)', '', path.read_text(), flags=re.M)
            if '[dependencies]' not in text: text += '\n[dependencies]\n'
            text += 'outside={' + ','.join(key + '=' + json.dumps(item) for key, item in value.items()) + '}\n'
            path.write_text(text, encoding='utf-8')
            return subprocess.CompletedProcess(command, 0, b'', b'')
        result = fixture.CargoNativeAuthoring.command(self, command, cwd, environment, seconds, maximum)
        if command[1] != 'metadata': return result
        from pathlib import Path
        app = Path(command[command.index('--manifest-path') + 1]).parent
        source = 'git+' + self.url + '?rev=' + self.rev + '#' + self.rev
        packages = [{'id': 'root', 'name': 'my-greeting', 'version': '1.0.0', 'source': None,
                     'manifest_path': str(app / 'Cargo.toml')},
                    {'id': 'git-package', 'name': 'outside', 'version': self.native_version,
                     'source': source, 'manifest_path': str(app.parent / 'git-cache/Cargo.toml')}]
        metadata = {'version': 1, 'packages': packages, 'resolve': {'root': 'root', 'nodes': [
            {'id': 'root', 'features': [], 'deps': [{'pkg': 'git-package', 'name': 'outside',
                                                  'dep_kinds': [{'kind': None, 'target': None}]}]},
            {'id': 'git-package', 'features': [], 'deps': []}]}}
        row = {'name': 'outside', 'version': self.native_version, 'source': source}
        self.alter_lock(row)
        with (app / 'Cargo.lock').open('a', encoding='utf-8') as target:
            for _ in range(2 if row.pop('duplicate', False) else 1):
                target.write('\n[[package]]\n' + ''.join(key + '=' + json.dumps(item) + '\n' for key, item in row.items()))
        self.alter_metadata(metadata)
        return subprocess.CompletedProcess(command, 0, canonical(metadata), b'')

    def selected(self, operation='add', **values):
        return self.author(operation, identity='outside', version='1.0.0', git=self.url, revision=self.rev, **values)

    def unchanged_on_denial(self, expected, **arguments):
        before = {name: (self.app / name).read_bytes() for name in ('Cargo.toml', 'Cargo.lock', 'sdk-lock.json')}
        with self.assertRaisesRegex(DependencyError, expected): self.selected(**arguments)
        self.assertEqual({name: (self.app / name).read_bytes() for name in before}, before)

    def test_add_and_revision_update_preserve_sdk_and_require_fresh_capture(self):
        accepted = self.app / 'latent.dependencies.lock.json'; accepted.write_bytes(b'previous reviewed capture')
        sdk = (self.app / 'sdk-lock.json').read_bytes()
        result = self.selected()
        self.assertTrue(result['captureRequired'] and result['reviewRequired'])
        self.assertFalse(result['compilerExecution'])
        row = tomllib.loads((self.app / 'Cargo.toml').read_text())['dependencies']['outside']
        self.assertEqual(row, {'git': self.url, 'rev': self.rev})
        self.rev = 'b' * 40
        self.selected('update')
        self.assertEqual(tomllib.loads((self.app / 'Cargo.toml').read_text())['dependencies']['outside']['rev'], self.rev)
        self.assertEqual((self.app / 'sdk-lock.json').read_bytes(), sdk)
        self.assertEqual(accepted.read_bytes(), b'previous reviewed capture')
        self.assertEqual([cmd[2] for cmd, *_ in self.commands if cmd[1] == 'add'], ['outside', 'outside'])

    def test_invalid_secret_unpinned_or_mutually_exclusive_selection_fails_before_native_work(self):
        variants = [{'git': None}, {'revision': None}, {'revision': 'a' * 7}, {'revision': 'A' * 40},
                    {'local': self.library}, {'registry': 'crates-io'}, {'git': 'http://example.test/repo'},
                    {'git': 'file:///owned/repo'}, {'git': 'ssh://example.test/repo'},
                    {'git': 'https://user:private@example.test/repo'}, {'git': 'https://example.test/repo?secret=x'},
                    {'git': 'https://example.test/repo#branch'}, {'git': 'https://example.test:bad/repo'},
                    {'git': 'https://example.test/repo\nprivate'}, {'git': []}]
        for changed in variants:
            arguments = {'identity': 'outside', 'version': '1.0.0', 'git': self.url, 'revision': self.rev, **changed}
            with self.subTest(changed=changed), patch.object(authoring, 'run_bounded') as run:
                with self.assertRaisesRegex(DependencyError, '^cargo-native-authoring-git-selection-invalid$'):
                    authoring.author(self.owner, 'add', **arguments)
                run.assert_not_called()

    def test_native_default_https_port_and_root_path_normalization_keep_exact_commit(self):
        self.url = 'https://EXAMPLE.test:443'
        source = 'git+https://example.test/?rev=' + self.rev + '#' + self.rev
        self.alter_metadata = lambda value: value['packages'][1].update(source=source)
        self.alter_lock = lambda value: value.update(source=source)
        self.selected()
        row = tomllib.loads((self.app / 'Cargo.toml').read_text())['dependencies']['outside']
        self.assertEqual(row, {'git': self.url, 'rev': self.rev})

    def test_native_metadata_must_bind_direct_package_version_source_and_exact_revision(self):
        mutations = [lambda m: m['packages'][1].update(version='9.9.9'),
                     lambda m: m['packages'][1].update(source='registry+https://example.test/index'),
                     lambda m: m['packages'][1].update(source='git+https://other.test/repo?rev='+self.rev+'#'+self.rev),
                     lambda m: m['packages'][1].update(source='git+'+self.url+'?rev='+self.rev+'#'+'c'*40),
                     lambda m: m['resolve']['nodes'][0].update(deps=[])]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                self.alter_metadata = mutate
                self.unchanged_on_denial('^cargo-native-authoring-native-selection-mismatch$')

    def test_native_manifest_cannot_substitute_another_source_or_reference(self):
        for row in ({'git': 'https://other.test/repo'}, {'rev': 'c' * 40}, {'branch': 'main'},
                    {'tag': 'v1'}, {'path': '../unselected'}, {'registry': 'crates-io'}, {'version': '9.9.9'}):
            with self.subTest(row=row):
                self.declaration = row
                reason = ('^cargo-path-dependency-not-in-selected-graph$' if 'path' in row else
                          '^cargo-native-authoring-native-selection-mismatch$')
                self.unchanged_on_denial(reason)

    def test_native_lock_must_contain_one_exact_selected_git_package(self):
        mutations = [lambda r: r.update(version='9.9.9'), lambda r: r.update(source='git+https://other.test/repo'),
                     lambda r: r.update(duplicate=True)]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                self.alter_lock = mutate
                self.unchanged_on_denial('^cargo-native-authoring-native-selection-mismatch$')

    def test_cli_routes_git_and_revision_to_the_existing_transaction(self):
        with patch.object(authoring, 'author', return_value={'status': 'locked'}) as call:
            from contextlib import redirect_stdout
            import io
            with redirect_stdout(io.StringIO()):
                self.assertEqual(rust_capsule.main(['add', str(self.owner), 'outside', '--version', '1.0.0',
                                                   '--git', self.url, '--rev', self.rev]), 0)
        self.assertEqual(call.call_args.kwargs['git'], self.url)
        self.assertEqual(call.call_args.kwargs['revision'], self.rev)


if __name__ == '__main__':
    unittest.main()
