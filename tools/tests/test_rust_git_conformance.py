"""Git campaign boundary controls; native results here are modelled, not executed."""
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tools import qualify_rust_git_dependencies as campaign


class GitOfflineMetadata(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='git-offline-source-control-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.project = self.root / 'app'
        self.project.mkdir()
        (self.project / 'Cargo.toml').write_bytes(b'[package]\nname="fixture"\nversion="1.0.0"\n')
        (self.project / 'rust-toolchain.toml').write_bytes(b'[toolchain]\nchannel="1.97.1"\n')
        self.cargo = self.root / 'cargo'
        self.cargo.write_bytes(b'fixture identity; never executed')
        self.closure = SimpleNamespace(identity='sha256:' + 'a' * 64, check_unchanged=Mock())
        self.mutate = lambda work, environment: None
        self.native_calls = []

    def configure(self, closure, work, home):
        self.assertIs(closure, self.closure)
        self.assertFalse(home.exists())
        home.mkdir()
        (home / 'config.toml').write_bytes(b'[net]\noffline=true\n')
        return b'fixture adapted manifest', {'networkResolution': False}

    def command(self, command, work, environment, seconds, maximum):
        self.native_calls.append(command)
        self.assertEqual(command, [str(self.cargo), 'metadata', '--manifest-path', str(work / 'Cargo.toml'),
                                  '--locked', '--offline', '--format-version', '1',
                                  '--filter-platform', 'wasm32-unknown-unknown'])
        self.assertEqual(seconds, 120)
        self.assertEqual(maximum, campaign.native.MAX_METADATA_BYTES)
        self.assertEqual(environment['CARGO_NET_OFFLINE'], 'true')
        self.assertEqual(environment['RUSTUP_AUTO_INSTALL'], '0')
        self.assertEqual(environment['RUSTUP_TOOLCHAIN'], '1.97.1')
        self.assertNotEqual(Path(environment['CARGO_HOME']), self.project)
        self.assertEqual(Path(environment['GIT_CONFIG_GLOBAL']).read_bytes(), b'')
        self.assertEqual(environment['GIT_CONFIG_NOSYSTEM'], '1')
        self.assertEqual(environment['GIT_TERMINAL_PROMPT'], '0')
        self.mutate(work, environment)
        return subprocess.CompletedProcess(command, 0, b'{"model-only-native-metadata":true}', b'')

    def invoke(self, name='offline'):
        with patch.object(campaign.dependencies, 'prepare', return_value=self.closure) as prepare, \
                patch.object(campaign.native, 'configure', side_effect=self.configure), \
                patch.object(campaign, 'run_bounded', side_effect=self.command), \
                patch.object(campaign.authoring, 'selected_git', return_value='model-only-exact-source') as selected:
            result = campaign.offline(self.project, self.root / name, self.cargo, *campaign.REVISIONS[1])
        prepare.assert_called_once_with(self.project, self.root / name / 'source', self.root / name, 'rust')
        selected.assert_called_once_with(b'{"model-only-native-metadata":true}', self.root / name / 'source',
                                        campaign.PACKAGE, campaign.REVISIONS[1][0], campaign.REPOSITORY,
                                        campaign.REVISIONS[1][1])
        return result

    def test_only_locked_offline_metadata_uses_verified_objects_and_a_fresh_home(self):
        result = self.invoke()
        self.assertEqual(result['status'], 'passed')
        self.assertFalse(result['applicationCompilation'])
        self.assertFalse(result['networkResolution'])
        self.assertTrue(result['freshCargoHome'] and result['sourceCachePayloadsAbsent'])
        self.closure.check_unchanged.assert_called_once_with()

    def test_a_git_or_registry_cache_cannot_satisfy_the_fresh_home_gate(self):
        for cache in ('git', 'registry'):
            def populate(work, environment, cache=cache):
                directory = Path(environment['CARGO_HOME']) / cache
                directory.mkdir()
                (directory / 'cached-source.rs').write_bytes(b'unreviewed source cache')
            self.mutate = populate
            with self.subTest(cache=cache), self.assertRaisesRegex(ValueError, '^Git-offline-cache-was-populated$'):
                self.invoke(cache)

    def test_native_cargo_cache_tags_and_empty_directories_are_bookkeeping_only(self):
        for cache in ('git', 'registry'):
            for tag in (False, True):
                def initialize(work, environment, cache=cache, tag=tag):
                    directory = Path(environment['CARGO_HOME']) / cache
                    directory.mkdir()
                    if tag:
                        (directory / 'CACHEDIR.TAG').write_bytes(campaign.CACHE_TAG)
                self.mutate = initialize
                with self.subTest(cache=cache, tag=tag):
                    result = self.invoke(f'{cache}-{tag}')
                    self.assertTrue(result['sourceCachePayloadsAbsent'])
                    self.assertEqual([row['path'] for row in result['cargoCacheBookkeeping']],
                                     [cache + '/CACHEDIR.TAG'] if tag else [])

    def test_cache_tags_have_exact_bounded_contents_and_no_extra_entries(self):
        for index, mutation in enumerate(('wrong-tag', 'over-bound', 'extra-entry', 'tag-directory')):
            def initialize(work, environment, mutation=mutation):
                directory = Path(environment['CARGO_HOME']) / 'registry'
                directory.mkdir()
                tag = directory / 'CACHEDIR.TAG'
                if mutation == 'tag-directory':
                    tag.mkdir()
                else:
                    tag.write_bytes(b'private unknown tag' if mutation == 'wrong-tag' else
                                    campaign.CACHE_TAG + (b'x' if mutation == 'over-bound' else b''))
                if mutation == 'extra-entry':
                    (directory / 'source.rs').write_bytes(b'unreviewed source cache')
            self.mutate = initialize
            with self.subTest(mutation=mutation), self.assertRaisesRegex(ValueError, '^Git-offline-cache-was-populated$'):
                self.invoke(f'invalid-{index}')

    def test_offline_observation_cannot_mutate_the_original_application(self):
        self.mutate = lambda work, environment: (self.project / 'Cargo.toml').write_bytes(b'changed input')
        with self.assertRaisesRegex(ValueError, '^Git-offline-original-project-mutated$'):
            self.invoke()

    def test_an_absent_reviewed_closure_cannot_reach_native_metadata(self):
        with patch.object(campaign.dependencies, 'prepare', return_value=None), \
                patch.object(campaign, 'run_bounded') as run:
            with self.assertRaisesRegex(ValueError, '^Git-reviewed-closure-missing$'):
                campaign.offline(self.project, self.root / 'missing', self.cargo, *campaign.REVISIONS[0])
        run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
