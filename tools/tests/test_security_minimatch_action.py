from __future__ import annotations

import copy
import hashlib
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


class MinMatchActionSourceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='lsf-minimatch-action-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        shutil.copytree(ROOT / '.github/security', self.root / '.github/security')
        self.controls = self.root / '.github/security'
        inventory = json.loads(read_file(self.root, '.github/security/inventory.json'))
        self.entry = next(entry for entry in inventory['manifests'] if entry['path'] == sources.MINIMATCH_PREFIX + 'package.json')
        patcher = patch.object(sources, 'POLICY', self.controls)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.runtime = {row['source']: ('hermetic runtime ' + name).encode()
                        for name, row in sources.MINIMATCH_RUNTIME.items()}
        runtime_policy = {name: {'source': row['source'], **sources.source_identity(self.runtime[row['source']])}
                          for name, row in sources.MINIMATCH_RUNTIME.items()}
        policy_path = self.controls / 'minimatch-action-source-repairs.json'
        policy = json.loads(policy_path.read_bytes())
        policy['runtime'] = runtime_policy
        build_path = self.root / sources.MINIMATCH_ASSETS['build']['snapshot']
        build = json.loads(build_path.read_bytes())
        for row in runtime_policy.values():
            build['artifact']['payloads'][row['source']] = {key: row[key] for key in ('bytes', 'sha256')}
        build_path.write_text(json.dumps(build), encoding='utf-8')
        asset_policy = copy.deepcopy(sources.MINIMATCH_ASSETS)
        asset_policy['build'].update(sources.source_identity(build_path.read_bytes()))
        policy['assets'] = asset_policy
        policy_path.write_text(json.dumps(policy), encoding='utf-8')
        runtime_patch = patch.object(sources, 'MINIMATCH_RUNTIME', runtime_policy)
        runtime_patch.start()
        self.addCleanup(runtime_patch.stop)
        assets_patch = patch.object(sources, 'MINIMATCH_ASSETS', asset_policy)
        assets_patch.start()
        self.addCleanup(assets_patch.stop)

    def fetch_runtime(self, reference, source):
        self.assertEqual(reference, sources.ACTION_REFERENCES[sources.MINIMATCH_PREFIX])
        return self.runtime[source]

    def fetch(self, pin):
        if pin['name'] == 'deepmerge':
            return read_file(self.root, '.github/security/actions/checkout-source/deepmerge-4.3.1.original.tgz')
        if pin['name'] == 'minimatch':
            return read_file(self.root, sources.MINIMATCH_ASSETS['upstream']['snapshot'])
        raise AssertionError('unexpected registry source')

    def verify(self):
        packages = npm_packages(self.root, self.entry)
        return sources.verify_sources(self.root, packages, {'manifests': [self.entry]}, self.fetch, self.fetch_runtime)

    def rebind(self, snapshot):
        path = self.root / '.github/security/actions.json'
        actions = json.loads(path.read_bytes())
        row = actions['actions'][sources.ACTION_REFERENCES[sources.MINIMATCH_PREFIX]]
        item = next(item for item in row['files'] if item['snapshot'] == snapshot)
        digest = hashlib.sha256((self.root / snapshot).read_bytes()).hexdigest()
        item['sha256'] = item['source_sha256'] = digest
        path.write_text(json.dumps(actions), encoding='utf-8')

    def test_reconstructed_source_receipt_only_resolves_exact_version_path_and_revision(self):
        receipts = self.verify()
        self.assertEqual({receipt['name'] for receipt in receipts}, {'deepmerge', 'minimatch'})
        fixed = next(receipt for receipt in receipts if receipt['name'] == 'minimatch')
        self.assertEqual(fixed['action'], sources.ACTION_REFERENCES[sources.MINIMATCH_PREFIX])
        self.assertEqual(fixed['locks'], [self.entry['lock']])
        known = finding('osv', 'GHSA-g3hv-75wg-m249', self.entry['lock'], 'npm:minimatch@10.2.5')
        foreign = finding('osv', known.finding, '.github/security/actions/setup-node/package-lock.json', known.package)
        version = finding('osv', known.finding, self.entry['lock'], 'npm:minimatch@10.2.6')
        new_advisory = finding('osv', 'GHSA-other-advisory', self.entry['lock'], known.package)
        obs = [{'advisories': [{'package': Package('npm', 'minimatch', '10.2.5', self.entry['lock']).public(), **fixed['advisories'][0]}]}]
        self.assertEqual(sources.resolve_findings([known, foreign, version, new_advisory], obs, receipts),
                         ([foreign, version, new_advisory], [known]))
        obs[0]['advisories'][0]['modified'] = 'future-revision'
        self.assertEqual(sources.resolve_findings([known], obs, receipts), ([known], []))

    def test_asset_policy_action_and_installed_runtime_drift_fail_closed(self):
        paths = [row['snapshot'] for row in sources.MINIMATCH_ASSETS.values()]
        paths += ['.github/security/minimatch-action-source-repairs.json', '.github/security/actions.json']
        for name in paths:
            with self.subTest(path=name):
                target = self.root / name
                before = target.read_bytes()
                try:
                    target.write_bytes(before + b'drift')
                    with self.assertRaises((SecurityError, ValueError)):
                        self.verify()
                finally:
                    target.write_bytes(before)
        self.assertEqual(len(self.verify()), 2)

    def test_duplicate_unpatched_or_changed_version_fails_even_with_rebound_snapshot(self):
        snapshot = self.entry['lock']
        path = self.root / snapshot
        actions_path = self.root / '.github/security/actions.json'
        original, actions_original = path.read_bytes(), actions_path.read_bytes()
        cases = ('duplicate', 'version', 'alias', 'integrity')
        for case in cases:
            with self.subTest(case=case):
                data = json.loads(original)
                row = data['packages']['node_modules/minimatch']
                if case == 'duplicate':
                    data['packages']['node_modules/extra/node_modules/minimatch'] = {
                        **row, 'resolved': 'https://registry.npmjs.org/minimatch/-/minimatch-10.2.5.tgz'}
                elif case == 'version':
                    row['version'] = '10.2.6'
                elif case == 'alias':
                    data['packages']['node_modules/alias'] = {**row, 'name': 'minimatch'}
                else:
                    row['integrity'] = 'sha512-untrusted'
                try:
                    path.write_text(json.dumps(data), encoding='utf-8')
                    self.rebind(snapshot)
                    with self.assertRaisesRegex(SecurityError, 'minimatch-action-source-graph'):
                        self.verify()
                finally:
                    path.write_bytes(original)
                    actions_path.write_bytes(actions_original)

    def test_owner_override_and_build_verifier_are_required_even_with_rebound_manifest(self):
        snapshot = self.entry['path']
        path = self.root / snapshot
        actions_path = self.root / '.github/security/actions.json'
        original, actions_original = path.read_bytes(), actions_path.read_bytes()
        for case in ('override', 'build', 'release', 'security-test'):
            with self.subTest(case=case):
                data = json.loads(original)
                if case == 'override':
                    del data['overrides']['minimatch@10']
                elif case == 'security-test':
                    del data['scripts']['test:security-source']
                else:
                    data['scripts'][case] = data['scripts'][case].replace('node .lsf-source/verify-installed-minimatch.mjs && ', '')
                try:
                    path.write_text(json.dumps(data), encoding='utf-8')
                    self.rebind(snapshot)
                    with self.assertRaisesRegex(SecurityError, 'minimatch-action-(source-graph|build-contract)'):
                        self.verify()
                finally:
                    path.write_bytes(original)
                    actions_path.write_bytes(actions_original)

    def test_policy_cannot_rebind_changed_source_or_expand_advisory_revision(self):
        policy_path = self.root / '.github/security/minimatch-action-source-repairs.json'
        actions_path = self.root / '.github/security/actions.json'
        policy_original, actions_original = policy_path.read_bytes(), actions_path.read_bytes()
        for asset in ('repair', 'archive', 'build'):
            with self.subTest(asset=asset):
                row = sources.MINIMATCH_ASSETS[asset]
                target = self.root / row['snapshot']
                before = target.read_bytes()
                try:
                    changed = before + b'drift'
                    target.write_bytes(changed)
                    policy = json.loads(policy_original)
                    policy['assets'][asset].update(bytes=len(changed), sha256=hashlib.sha256(changed).hexdigest(),
                        gitBlob=hashlib.sha1(b'blob ' + str(len(changed)).encode() + b'\0' + changed).hexdigest())
                    policy_path.write_text(json.dumps(policy), encoding='utf-8')
                    with self.assertRaisesRegex(SecurityError, 'minimatch-action-policy'):
                        self.verify()
                finally:
                    target.write_bytes(before)
                    policy_path.write_bytes(policy_original)
                    actions_path.write_bytes(actions_original)
        for change in ('runtime', 'advisory'):
            policy = json.loads(policy_original)
            if change == 'runtime':
                policy['runtime']['runtime_setup']['sha256'] = '0' * 64
            else:
                policy['advisories'][0]['modified'] = 'future-revision'
            policy_path.write_text(json.dumps(policy), encoding='utf-8')
            with self.assertRaisesRegex(SecurityError, 'minimatch-action-policy'):
                self.verify()

    def test_changed_or_unavailable_runtime_cannot_issue_receipt(self):
        packages = npm_packages(self.root, self.entry)
        with self.assertRaisesRegex(SecurityError, 'minimatch-action-runtime-drift'):
            sources.verify_sources(self.root, packages, {'manifests': [self.entry]}, self.fetch,
                                   lambda reference, source: b'changed runtime')
        def unavailable(reference, source):
            raise OSError('fixture unavailable')
        with self.assertRaises(OSError):
            sources.verify_sources(self.root, packages, {'manifests': [self.entry]}, self.fetch, unavailable)

    def test_runtime_fetch_is_immutable_bounded_and_rejects_redirects(self):
        reference = sources.ACTION_REFERENCES[sources.MINIMATCH_PREFIX]
        source = 'dist/setup/index.js'
        class Response:
            status = 200
            def __init__(self, url, mode):
                self.url = url + ('/redirect' if mode == 'redirect' else '')
                self.mode = mode
                self.remaining = (sources.MINIMATCH_RUNTIME_LIMIT + 1 if mode == 'oversized'
                                  else 0 if mode == 'empty' else 1)
                if mode == 'status':
                    self.status = 403
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read1(self, size):
                if not self.remaining:
                    return b''
                if self.mode == 'oversized':
                    length = min(self.remaining, size)
                    self.remaining -= length
                    return b'x' * length
                self.remaining = 0
                return b'fixture'
        class Opener:
            def __init__(self, mode):
                self.mode = mode
            def open(self, url, timeout):
                self_url = ('https://raw.githubusercontent.com/' + reference.replace('@', '/') + '/' + source)
                self.assertions(url, timeout, self_url)
                if self.mode == 'unavailable':
                    raise OSError('fixture unavailable')
                return Response(url, self.mode)
            @staticmethod
            def assertions(url, timeout, expected):
                assert url == expected and timeout == 30
        for mode in ('ok', 'redirect', 'status', 'oversized', 'unavailable'):
            with self.subTest(mode=mode), patch.object(sources.urllib.request, 'build_opener', return_value=Opener(mode)):
                if mode == 'ok':
                    self.assertEqual(sources.action_runtime(reference, source), b'fixture')
                elif mode == 'unavailable':
                    with self.assertRaises(OSError):
                        sources.action_runtime(reference, source)
                else:
                    with self.assertRaises(SecurityError):
                        sources.action_runtime(reference, source)
        with patch.object(sources.urllib.request, 'build_opener', return_value=Opener('ok')):
            with patch.object(sources, 'monotonic', side_effect=[0, 0, 31]):
                with self.assertRaisesRegex(SecurityError, 'minimatch-action-runtime-deadline'):
                    sources.action_runtime(reference, source)
        with patch.object(sources.urllib.request, 'build_opener', return_value=Opener('empty')):
            with patch.object(sources, 'monotonic', side_effect=[0, 0, 31]):
                with self.assertRaisesRegex(SecurityError, 'minimatch-action-runtime-deadline'):
                    sources.action_runtime(reference, source)
        class MissingRead1:
            status = 200
            def __init__(self, url):
                self.url = url
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
        class IncompleteOpener:
            def open(self, url, timeout):
                return MissingRead1(url)
        with patch.object(sources.urllib.request, 'build_opener', return_value=IncompleteOpener()):
            with self.assertRaises(AttributeError):
                sources.action_runtime(reference, source)
        with self.assertRaises(ValueError):
            sources.NoRedirect().redirect_request(None, None, None, None, None, None)
        with self.assertRaises(SecurityError):
            sources.action_runtime('other/action@' + 'a' * 40, source)
        with self.assertRaises(SecurityError):
            sources.action_runtime(reference, 'dist/unreviewed.js')

    def test_missing_unselected_profile_and_upstream_mismatch_cannot_issue_receipt(self):
        foreign = copy.deepcopy(self.entry)
        foreign['path'] = '.github/security/actions/setup-node/package.json'
        foreign['lock'] = '.github/security/actions/setup-node/package-lock.json'
        with self.assertRaisesRegex(SecurityError, 'unreviewed-minimatch-action-profile'):
            sources.minimatch_action_inputs(self.root, foreign, {}, {})
        owner = json.loads(read_file(self.root, self.entry['path']))
        lock = json.loads(read_file(self.root, self.entry['lock']))
        unselected = copy.deepcopy(self.entry)
        del unselected['minimatch_source_repair']
        with self.assertRaises(SecurityError):
            sources.action_library_sources(self.root, unselected, owner, lock)
        packages = npm_packages(self.root, self.entry)
        with self.assertRaisesRegex(SecurityError, 'minimatch-action-upstream-drift'):
            sources.verify_sources(self.root, packages, {'manifests': [self.entry]},
                                   lambda pin: self.fetch(pin) + (b'drift' if pin['name'] == 'minimatch' else b''),
                                   self.fetch_runtime)


if __name__ == '__main__':
    unittest.main()
