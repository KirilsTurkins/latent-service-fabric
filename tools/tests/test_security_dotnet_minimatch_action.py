"""Fail-closed source and runtime receipts for the setup-dotnet matcher repair."""
import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from tools import security_dotnet_minimatch as profile
from tools import security_npm_sources as sources
from tools.security_common import ROOT, SecurityError, read_file
from tools.security_findings import finding
from tools.security_inventory import Package, npm_packages


class DotnetMinimatchActionSourceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='lsf-dotnet-minimatch-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        shutil.copytree(ROOT / '.github/security', self.root / '.github/security')
        controls = self.root / '.github/security'
        inventory = json.loads(read_file(self.root, '.github/security/inventory.json'))
        self.entry = next(row for row in inventory['manifests'] if row['path'] == profile.PREFIX + 'package.json')
        patcher = patch.object(sources, 'POLICY', controls)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.runtime = {row['source']: ('hermetic dotnet runtime ' + name).encode()
                        for name, row in profile.RUNTIME.items()}
        runtime_policy = {name: {'source': row['source'], **sources.source_identity(self.runtime[row['source']])}
                          for name, row in profile.RUNTIME.items()}
        policy_path = controls / 'minimatch-dotnet-action-source-repairs.json'
        policy = json.loads(policy_path.read_bytes())
        build_path = self.root / profile.ASSETS['build']['snapshot']
        build = json.loads(build_path.read_bytes())
        build['outputs'] = {row['source']: {key: row[key] for key in ('bytes', 'sha256', 'gitBlob')}
                            for row in runtime_policy.values()}
        build_path.write_text(json.dumps(build), encoding='utf-8')
        asset_policy = copy.deepcopy(profile.ASSETS)
        asset_policy['build'].update(sources.source_identity(build_path.read_bytes()))
        policy['assets'], policy['runtime'] = asset_policy, runtime_policy
        policy_path.write_text(json.dumps(policy), encoding='utf-8')
        for name, value in (('RUNTIME', runtime_policy), ('ASSETS', asset_policy)):
            patcher = patch.object(profile, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def fetch(self, pin):
        if pin['name'] == 'deepmerge':
            return read_file(self.root, '.github/security/actions/checkout-source/deepmerge-4.3.1.original.tgz')
        if pin['name'] == 'minimatch':
            return read_file(self.root, profile.ASSETS['upstream']['snapshot'])
        raise AssertionError('unexpected registry source')

    def fetch_runtime(self, reference, source):
        self.assertEqual(reference, profile.REFERENCE)
        return self.runtime[source]

    def verify(self, fetch_runtime=None):
        packages = npm_packages(self.root, self.entry)
        return sources.verify_sources(self.root, packages, {'manifests': [self.entry]}, self.fetch,
                                      fetch_runtime or self.fetch_runtime)

    def rebind(self, snapshot):
        path = self.root / '.github/security/actions.json'
        actions = json.loads(path.read_bytes())
        row = actions['actions'][profile.REFERENCE]
        item = next(item for item in row['files'] if item['snapshot'] == snapshot)
        item['sha256'] = item['source_sha256'] = sources.digest((self.root / snapshot).read_bytes())
        if row['metadata']['snapshot'] == snapshot:
            row['metadata'] = dict(item)
        path.write_text(json.dumps(actions), encoding='utf-8')

    def test_only_exact_lock_versions_and_advisory_revisions_receive_receipts(self):
        receipts = self.verify()
        self.assertEqual({row['name'] for row in receipts}, {'deepmerge', 'minimatch'})
        for receipt in receipts:
            version, name = receipt['version'], receipt['name']
            known = finding('osv', receipt['advisories'][0]['id'], self.entry['lock'], f'npm:{name}@{version}')
            foreign = finding('osv', known.finding, '.github/security/actions/setup-python/package-lock.json', known.package)
            wrong_version = finding('osv', known.finding, self.entry['lock'], f'npm:{name}@99.0.0')
            other = finding('osv', 'GHSA-unreviewed', self.entry['lock'], known.package)
            observations = [{'advisories': [{'package': Package('npm', name, version, self.entry['lock']).public(),
                                             **receipt['advisories'][0]}]}]
            self.assertEqual(sources.resolve_findings([known, foreign, wrong_version, other], observations, receipts),
                             ([foreign, wrong_version, other], [known]))
            observations[0]['advisories'][0]['modified'] = 'future-revision'
            self.assertEqual(sources.resolve_findings([known], observations, receipts), ([known], []))

    def test_each_runtime_rejects_changed_or_unavailable_bytes(self):
        for target in self.runtime:
            def changed(reference, path):
                return self.fetch_runtime(reference, path) + (b'drift' if path == target else b'')
            with self.subTest(path=target), self.assertRaisesRegex(SecurityError, 'dotnet-minimatch-action-runtime-drift'):
                self.verify(changed)
        def unavailable(reference, path):
            raise OSError('fixture unavailable')
        with self.assertRaises(OSError):
            self.verify(unavailable)

    def test_asset_and_policy_rebinding_cannot_forge_source_or_receipt(self):
        policy_path = self.root / '.github/security/minimatch-dotnet-action-source-repairs.json'
        policy_before = policy_path.read_bytes()
        actions_path = self.root / '.github/security/actions.json'
        actions_before = actions_path.read_bytes()
        for name, binding in profile.ASSETS.items():
            with self.subTest(asset=name):
                target = self.root / binding['snapshot']
                before = target.read_bytes()
                try:
                    target.write_bytes(before + b'drift')
                    with self.assertRaises((SecurityError, ValueError)):
                        self.verify()
                    policy = json.loads(policy_before)
                    policy['assets'][name].update(sources.source_identity(target.read_bytes()))
                    policy_path.write_text(json.dumps(policy), encoding='utf-8')
                    if name in ('verifier', 'tests'):
                        self.rebind(binding['snapshot'])
                    with self.assertRaisesRegex(SecurityError, 'dotnet-minimatch-action-policy|action-source-binding-drift'):
                        self.verify()
                finally:
                    target.write_bytes(before)
                    policy_path.write_bytes(policy_before)
                    actions_path.write_bytes(actions_before)
        for change in ('advisory', 'runtime', 'action'):
            with self.subTest(policy=change):
                policy = json.loads(policy_before)
                if change == 'advisory': policy['advisories'][0]['modified'] = 'future-revision'
                elif change == 'runtime': policy['runtime']['runtime_setup']['sha256'] = '0' * 64
                else: policy['action'] = policy['action'].replace('2382c9e6', 'f5bcdac7')
                policy_path.write_text(json.dumps(policy), encoding='utf-8')
                with self.assertRaisesRegex(SecurityError, 'dotnet-minimatch-action-policy'):
                    self.verify()
                policy_path.write_bytes(policy_before)

    def test_source_and_registry_hash_cannot_be_forged_together(self):
        actions_path = self.root / '.github/security/actions.json'
        actions_before = actions_path.read_bytes()
        for source in ('action.yml', 'package.json', 'package-lock.json', '.lsf-source/verify-installed-deepmerge.mjs',
                       '.lsf-source/verify-installed-minimatch.mjs', '.lsf-source/minimatch-bounds.test.mjs'):
            with self.subTest(source=source):
                row = json.loads(actions_before)['actions'][profile.REFERENCE]
                snapshot = next(item['snapshot'] for item in row['files'] if item['source'] == source)
                target = self.root / snapshot
                before = target.read_bytes()
                try:
                    target.write_bytes(before + b'\n ')
                    self.rebind(snapshot)
                    with self.assertRaises((SecurityError, ValueError)):
                        self.verify()
                finally:
                    target.write_bytes(before)
                    actions_path.write_bytes(actions_before)

    def test_duplicate_alias_changed_graph_and_commands_are_refused(self):
        owner = json.loads(read_file(self.root, self.entry['path']))
        lock = json.loads(read_file(self.root, self.entry['lock']))
        for change in ('duplicate', 'alias', 'version', 'integrity', 'glob-runtime', 'glob-build', 'override', 'build', 'test'):
            with self.subTest(change=change):
                o, l = copy.deepcopy(owner), copy.deepcopy(lock)
                row = l['packages']['node_modules/minimatch']
                if change == 'duplicate': l['packages']['node_modules/other/node_modules/minimatch'] = dict(row)
                elif change == 'alias': l['packages']['node_modules/other'] = {**row, 'name': 'minimatch'}
                elif change == 'version': row['version'] = '10.2.6'
                elif change == 'integrity': row['integrity'] = 'sha512-bad'
                elif change == 'glob-runtime': l['packages']['node_modules/@actions/glob']['dependencies']['minimatch'] = '^11'
                elif change == 'glob-build': l['packages']['node_modules/glob']['dev'] = False
                elif change == 'override': del o['overrides']['minimatch@10']
                elif change == 'build': o['scripts']['build'] = 'true'
                elif change == 'test': o['scripts']['test:security-source'] = 'true'
                with self.assertRaises(SecurityError):
                    profile.action_inputs(self.root, self.entry, o, l)

    def test_only_exact_reference_and_paths_are_fetchable(self):
        class Response:
            status = 200
            def __init__(self, url): self.url, self.pending = url, True
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read1(self, size):
                if self.pending:
                    self.pending = False
                    return b'fixture'
                return b''
        class Opener:
            def open(self, url, timeout):
                assert timeout == 30
                return Response(url)
        with patch.object(sources.urllib.request, 'build_opener', return_value=Opener()):
            for path in self.runtime:
                self.assertEqual(sources.action_runtime(profile.REFERENCE, path), b'fixture')
            with self.assertRaises(SecurityError):
                sources.action_runtime(profile.REFERENCE.replace('2382c9e6', 'f5bcdac7'), 'dist/setup/index.js')
            with self.assertRaises(SecurityError):
                sources.action_runtime(profile.REFERENCE, 'dist/unreviewed.js')
            with self.assertRaises(SecurityError):
                sources.action_runtime(sources.ACTION_REFERENCES[sources.JAVA_MINIMATCH_PREFIX], 'dist/cache-save/index.js')

    def test_historical_projection_rejects_stale_or_mixed_dotnet_pins(self):
        from tools.tests.test_sdk_scratch_qualification import historical_security_actions
        previous = 'KirilsTurkins/lsf-setup-dotnet@f5bcdac7f26977ef44527f837688dd86faf648ec'
        self.assertEqual(historical_security_actions(profile.REFERENCE), previous)
        for invalid in (previous, profile.REFERENCE + '\n' + previous, profile.REFERENCE + 'suffix'):
            with self.subTest(value=invalid), self.assertRaisesRegex(
                    AssertionError, 'historical-workflow-exact-current-security-actions-required'):
                historical_security_actions(invalid)

    def test_historical_projection_rejects_stale_or_mixed_bytecode_pins(self):
        from tools.tests.test_sdk_scratch_qualification import historical_security_actions
        reference = 'KirilsTurkins/lsf-bytecodealliance-actions/wasm-tools/setup@1ce6e3461b7d83b4b5a5a6557870b4fdfd4386ce'
        previous = 'KirilsTurkins/lsf-bytecodealliance-actions/wasm-tools/setup@9244ec9f4725400c84054e3e6ec97514cadddf53'
        self.assertEqual(historical_security_actions(reference), previous)
        for invalid in (previous, reference + '\n' + previous, reference + 'suffix'):
            with self.subTest(value=invalid), self.assertRaisesRegex(
                    AssertionError, 'historical-workflow-exact-current-security-actions-required'):
                historical_security_actions(invalid)

    def test_duplicate_current_workflow_step_is_rejected_by_original_full_model_guard(self):
        from tools.tests import test_dotnet_http_mixed as mixed
        workflow = ROOT / '.github/workflows/dotnet-published-http.yml'
        text = workflow.read_text(encoding='utf-8')
        step = '      - uses: ' + profile.REFERENCE
        self.assertIn(step, text)
        before, marker, retained = text.partition('\n  published-http:\n')
        self.assertTrue(marker)
        self.assertIn(step, retained)
        duplicate = before + marker + retained.replace(step, step + '\n' + step, 1)
        target = self.root / '.github/workflows/dotnet-published-http.yml'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(duplicate, encoding='utf-8')
        case = mixed.DotnetHttpMixed('test_manual_only_selector_restores_entire_previous_workflow_without_any_step_changes')
        with patch.object(mixed, 'ROOT', self.root), self.assertRaises(AssertionError):
            case.test_manual_only_selector_restores_entire_previous_workflow_without_any_step_changes()

    def test_missing_selection_or_upstream_drift_cannot_issue_receipt(self):
        packages = npm_packages(self.root, self.entry)
        self.assertEqual(profile.verify_sources(self.root, [], {'manifests': [self.entry]}, self.fetch, self.fetch_runtime), [])
        foreign = copy.deepcopy(self.entry)
        foreign['path'], foreign['lock'] = sources.MINIMATCH_PREFIX + 'package.json', sources.MINIMATCH_PREFIX + 'package-lock.json'
        with self.assertRaisesRegex(SecurityError, 'unreviewed-minimatch-action-profile'):
            profile.action_inputs(self.root, foreign, {}, {})
        def changed(pin): return self.fetch(pin) + (b'drift' if pin['name'] == 'minimatch' else b'')
        with self.assertRaisesRegex(SecurityError, 'dotnet-minimatch-action-upstream-drift'):
            profile.verify_sources(self.root, packages, {'manifests': [self.entry]}, changed, self.fetch_runtime)
