"""Fail-closed source and runtime receipts for the setup-node matcher repair."""
import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from tools import security_npm_sources as sources
from tools.security_common import ROOT, SecurityError, read_file
from tools.security_findings import finding
from tools.security_inventory import Package, npm_packages


class NodeMinimatchActionSourceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='lsf-node-minimatch-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        shutil.copytree(ROOT / '.github/security', self.root / '.github/security')
        controls = self.root / '.github/security'
        inventory = json.loads(read_file(self.root, '.github/security/inventory.json'))
        self.entry = next(row for row in inventory['manifests']
                          if row['path'] == sources.NODE_MINIMATCH_PREFIX + 'package.json')
        patcher = patch.object(sources, 'POLICY', controls)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.runtime = {row['source']: ('hermetic Node runtime ' + name).encode()
                        for name, row in sources.NODE_MINIMATCH_RUNTIME.items()}
        runtime_policy = {name: {'source': row['source'], **sources.source_identity(self.runtime[row['source']])}
                          for name, row in sources.NODE_MINIMATCH_RUNTIME.items()}
        policy_path = controls / 'minimatch-node-action-source-repairs.json'
        policy = json.loads(policy_path.read_bytes())
        policy['runtime'] = runtime_policy
        build_path = self.root / sources.NODE_MINIMATCH_ASSETS['build']['snapshot']
        build = json.loads(build_path.read_bytes())
        for row in runtime_policy.values():
            build['artifact']['payloads'][row['source']] = {key: row[key] for key in ('bytes', 'sha256')}
        build_path.write_text(json.dumps(build), encoding='utf-8')
        asset_policy = copy.deepcopy(sources.NODE_MINIMATCH_ASSETS)
        asset_policy['build'].update(sources.source_identity(build_path.read_bytes()))
        policy['assets'] = asset_policy
        policy_path.write_text(json.dumps(policy), encoding='utf-8')
        for name, value in (('NODE_MINIMATCH_RUNTIME', runtime_policy), ('NODE_MINIMATCH_ASSETS', asset_policy)):
            patcher = patch.object(sources, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def fetch(self, pin):
        if pin['name'] == 'deepmerge':
            return read_file(self.root, '.github/security/actions/checkout-source/deepmerge-4.3.1.original.tgz')
        if pin['name'] == 'minimatch':
            return read_file(self.root, sources.NODE_MINIMATCH_ASSETS['upstream']['snapshot'])
        raise AssertionError('unexpected registry source')

    def fetch_runtime(self, reference, source):
        self.assertEqual(reference, sources.ACTION_REFERENCES[sources.NODE_MINIMATCH_PREFIX])
        return self.runtime[source]

    def verify(self, fetch_runtime=None):
        packages = npm_packages(self.root, self.entry)
        return sources.verify_sources(self.root, packages, {'manifests': [self.entry]}, self.fetch,
                                      fetch_runtime or self.fetch_runtime)

    def rebind(self, snapshot):
        path = self.root / '.github/security/actions.json'
        actions = json.loads(path.read_bytes())
        row = actions['actions'][sources.ACTION_REFERENCES[sources.NODE_MINIMATCH_PREFIX]]
        item = next(item for item in row['files'] if item['snapshot'] == snapshot)
        item['sha256'] = item['source_sha256'] = sources.digest((self.root / snapshot).read_bytes())
        path.write_text(json.dumps(actions), encoding='utf-8')

    def test_only_exact_lock_version_and_advisory_revision_receive_receipt(self):
        receipts = self.verify()
        self.assertEqual({row['name'] for row in receipts}, {'deepmerge', 'minimatch'})
        fixed = next(row for row in receipts if row['name'] == 'minimatch')
        self.assertEqual(fixed['action'], sources.ACTION_REFERENCES[sources.NODE_MINIMATCH_PREFIX])
        self.assertEqual(fixed['locks'], [self.entry['lock']])
        self.assertEqual(fixed['built_tree'], 'b1591bf1668591f5e54cfac62c28b70304661927')
        known = finding('osv', 'GHSA-g3hv-75wg-m249', self.entry['lock'], 'npm:minimatch@10.2.6')
        foreign = finding('osv', known.finding, '.github/security/actions/setup-java/package-lock.json', known.package)
        version = finding('osv', known.finding, self.entry['lock'], 'npm:minimatch@10.2.5')
        advisory = finding('osv', 'GHSA-other-advisory', self.entry['lock'], known.package)
        observations = [{'advisories': [{'package': Package('npm', 'minimatch', '10.2.6', self.entry['lock']).public(),
                                         **fixed['advisories'][0]}]}]
        self.assertEqual(sources.resolve_findings([known, foreign, version, advisory], observations, receipts),
                         ([foreign, version, advisory], [known]))
        observations[0]['advisories'][0]['modified'] = 'future-revision'
        self.assertEqual(sources.resolve_findings([known], observations, receipts), ([known], []))

    def test_every_runtime_file_rejects_drift_or_unavailability(self):
        for target in self.runtime:
            with self.subTest(path=target):
                def changed(reference, path):
                    return self.fetch_runtime(reference, path) + (b'drift' if path == target else b'')
                with self.assertRaisesRegex(SecurityError, 'node-minimatch-action-runtime-drift'):
                    self.verify(changed)
        def unavailable(reference, path):
            raise OSError('fixture unavailable')
        with self.assertRaises(OSError):
            self.verify(unavailable)

    def test_assets_policy_and_forged_rebindings_fail_closed(self):
        policy_path = self.root / '.github/security/minimatch-node-action-source-repairs.json'
        before_policy = policy_path.read_bytes()
        actions_path = self.root / '.github/security/actions.json'
        before_actions = actions_path.read_bytes()
        for name, binding in sources.NODE_MINIMATCH_ASSETS.items():
            with self.subTest(asset=name):
                target = self.root / binding['snapshot']
                before = target.read_bytes()
                try:
                    target.write_bytes(before + b'drift')
                    with self.assertRaises((SecurityError, ValueError)):
                        self.verify()
                    policy = json.loads(before_policy)
                    policy['assets'][name].update(sources.source_identity(target.read_bytes()))
                    policy_path.write_text(json.dumps(policy), encoding='utf-8')
                    if name in ('verifier', 'tests'):
                        self.rebind(binding['snapshot'])
                    with self.assertRaisesRegex(SecurityError, 'node-minimatch-action-policy'):
                        self.verify()
                finally:
                    target.write_bytes(before)
                    policy_path.write_bytes(before_policy)
                    actions_path.write_bytes(before_actions)
        for change in ('advisory', 'runtime', 'action'):
            with self.subTest(policy=change):
                policy = json.loads(before_policy)
                if change == 'advisory':
                    policy['advisories'][0]['modified'] = 'future-revision'
                elif change == 'runtime':
                    policy['runtime']['runtime_setup']['sha256'] = '0' * 64
                else:
                    policy['action'] = policy['action'].replace('34275fde', 'fdae00b1')
                policy_path.write_text(json.dumps(policy), encoding='utf-8')
                with self.assertRaisesRegex(SecurityError, 'node-minimatch-action-policy'):
                    self.verify()
                policy_path.write_bytes(before_policy)

    def test_duplicate_unpatched_and_changed_graphs_fail_even_after_rebinding(self):
        snapshot = self.entry['lock']
        target = self.root / snapshot
        actions_path = self.root / '.github/security/actions.json'
        before, actions_before = target.read_bytes(), actions_path.read_bytes()
        for change in ('duplicate', 'alias', 'version', 'integrity', 'glob', 'build-glob'):
            with self.subTest(change=change):
                lock = json.loads(before)
                row = lock['packages']['node_modules/minimatch']
                if change == 'duplicate':
                    lock['packages']['node_modules/foreign/node_modules/minimatch'] = {
                        **row, 'resolved': 'https://registry.npmjs.org/minimatch/-/minimatch-10.2.6.tgz'}
                elif change == 'alias':
                    lock['packages']['node_modules/alias'] = {**row, 'name': 'minimatch'}
                elif change == 'version':
                    row['version'] = '10.2.5'
                elif change == 'integrity':
                    row['integrity'] = 'sha512-untrusted'
                elif change == 'glob':
                    lock['packages']['node_modules/@actions/glob']['dependencies']['minimatch'] = '^11.0.0'
                else:
                    lock['packages']['node_modules/glob']['dev'] = False
                try:
                    target.write_text(json.dumps(lock), encoding='utf-8')
                    self.rebind(snapshot)
                    with self.assertRaises(SecurityError):
                        self.verify()
                finally:
                    target.write_bytes(before)
                    actions_path.write_bytes(actions_before)

    def test_build_and_source_verifiers_are_mandatory_after_manifest_rebinding(self):
        snapshot = self.entry['path']
        target = self.root / snapshot
        actions_path = self.root / '.github/security/actions.json'
        before, actions_before = target.read_bytes(), actions_path.read_bytes()
        for change in ('deepmerge', 'minimatch', 'override', 'glob-override', 'test', 'pre-checkin'):
            with self.subTest(change=change):
                owner = json.loads(before)
                if change == 'override':
                    del owner['overrides']['minimatch@10']
                elif change == 'glob-override':
                    del owner['overrides']['glob@10']
                elif change == 'test':
                    del owner['scripts']['test:security-source']
                elif change == 'pre-checkin':
                    owner['scripts']['pre-checkin'] = 'true'
                else:
                    fragment = {'deepmerge': 'node .lsf-source/verify-installed-deepmerge.mjs && ',
                                'minimatch': 'node .lsf-source/verify-installed-minimatch.mjs && '}[change]
                    owner['scripts']['build'] = owner['scripts']['build'].replace(fragment, '')
                try:
                    target.write_text(json.dumps(owner), encoding='utf-8')
                    self.rebind(snapshot)
                    with self.assertRaises(SecurityError):
                        self.verify()
                finally:
                    target.write_bytes(before)
                    actions_path.write_bytes(actions_before)

    def test_only_the_exact_node_reference_and_two_paths_are_fetchable(self):
        reference = sources.ACTION_REFERENCES[sources.NODE_MINIMATCH_PREFIX]
        class Response:
            status = 200
            def __init__(self, url):
                self.url, self.pending = url, True
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
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
                self.assertEqual(sources.action_runtime(reference, path), b'fixture')
            with self.assertRaises(SecurityError):
                sources.action_runtime(reference.replace('34275fde', 'fdae00b1'), 'dist/setup/index.js')
            with self.assertRaises(SecurityError):
                sources.action_runtime(reference, 'dist/unreviewed.js')
            with self.assertRaises(SecurityError):
                sources.action_runtime(reference, 'dist/setup/971.index.js')
            with self.assertRaises(SecurityError):
                sources.action_runtime(sources.ACTION_REFERENCES[sources.MINIMATCH_PREFIX],
                                       'dist/setup/971.index.js')

    def test_mixed_profile_and_registry_upstream_drift_cannot_issue_receipts(self):
        foreign = copy.deepcopy(self.entry)
        foreign['path'] = sources.MINIMATCH_PREFIX + 'package.json'
        foreign['lock'] = sources.MINIMATCH_PREFIX + 'package-lock.json'
        with self.assertRaisesRegex(SecurityError, 'unreviewed-minimatch-action-profile'):
            sources.minimatch_action_inputs(self.root, foreign, {}, {})
        unselected = copy.deepcopy(self.entry)
        del unselected['minimatch_source_repair']
        owner = json.loads(read_file(self.root, self.entry['path']))
        lock = json.loads(read_file(self.root, self.entry['lock']))
        with self.assertRaises(SecurityError):
            sources.action_library_sources(self.root, unselected, owner, lock)
        packages = npm_packages(self.root, self.entry)
        with self.assertRaisesRegex(SecurityError, 'node-minimatch-action-upstream-drift'):
            sources.verify_sources(self.root, packages, {'manifests': [self.entry]},
                                   lambda pin: self.fetch(pin) + (b'drift' if pin['name'] == 'minimatch' else b''),
                                   self.fetch_runtime)

    def test_historical_projection_rejects_stale_or_mixed_node_pins(self):
        from tools.tests.test_sdk_scratch_qualification import historical_security_actions
        reference = sources.ACTION_REFERENCES[sources.NODE_MINIMATCH_PREFIX]
        old = 'KirilsTurkins/lsf-setup-node@c1136b2d97fe79ef645e9508b2048a222f50a170'
        self.assertEqual(historical_security_actions(reference), old)
        stale = 'KirilsTurkins/lsf-setup-node@fdae00b14e855eb751452bc70c64dde286270415'
        for value in (stale, reference + '\n' + stale, reference + 'suffix'):
            with self.subTest(value=value), self.assertRaisesRegex(
                    AssertionError, 'historical-workflow-exact-current-security-actions-required'):
                historical_security_actions(value)


if __name__ == '__main__':
    unittest.main()
