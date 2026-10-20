"""The additive packet consumes exact observed normal products; it never builds a host."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tools import qualify_sdk_scratch as qualifier
from tools.native_runtime.common import InstallError
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_project import digest, inventory, write_json


def replace_json(path, value):
    path.write_bytes((json.dumps(value, sort_keys=True)+'\n').encode())


def ordinary(root):
    write_json(root/'source-inputs.json', {'source': 'original normal qualification'})
    (root/'native-binaries').mkdir()
    binaries = {}
    for name in qualifier.PRODUCTS:
        path = root/'native-binaries'/name.replace('/', '-')
        path.write_bytes(('observed-'+name).encode())
        binaries[name] = file_identity(path)
    builds = {}
    for name in qualifier.TEMPLATES:
        if name == 'greeting': continue
        directory = root/'builds'/name
        directory.mkdir(parents=True)
        (directory/'component.wasm').write_bytes(('actual-'+name).encode())
        (directory/'source-inputs.json').write_bytes(b'{}\n')
        write_json(directory/'package-source.json', {'layers': [{'source': 'component.wasm'}]})
        package = inventory({item: (directory/item).read_bytes() for item in ('component.wasm', 'package-source.json')})
        (directory/'package-inputs.json').write_bytes(package)
        write_json(directory/'build-observation.json', {'materials': [
            {'name': 'package-inputs', 'digest': digest(package), 'size': len(package)}]})
        builds[name] = {field: file_identity(directory/item)['sha256'] for item, field in (
            ('component.wasm', 'componentDigest'), ('source-inputs.json', 'sourceDigest'),
            ('build-observation.json', 'observationDigest'))}
        write_json(directory/'BUILD-COMPLETE.json', builds[name])
        write_json(directory/'deployment.json', {'original': name})
    (root/'node').mkdir()
    write_json(root/'node/workflow.json', {'status': 'passed', 'language': 'rust',
        'invocations': [{'original': index} for index in range(27)],
        'nodeShutdown': {'reaped': True, 'record': {'clean': True}}})
    record = {'schemaVersion': 'latent.rust-capsule.qualification.v1', 'status': 'passed',
        'sourceIdentityDigest': file_identity(root/'source-inputs.json')['sha256'],
        'binaries': binaries, 'builds': builds,
        'node': {'receiptDigest': file_identity(root/'node/workflow.json')['sha256']}}
    write_json(root/'qualification.json', record)
    return record


class ScratchQualification(unittest.TestCase):
    def test_exact_normal_native_companions_and_node_are_required_before_new_compile(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ordinary(root)
            with patch.object(qualifier, 'current_inputs', return_value={'source': 'original normal qualification'}):
                binaries, companions, observed = qualifier.prepared(root, 'rust')
            self.assertEqual(set(binaries), set(qualifier.PRODUCTS))
            self.assertEqual(set(companions), set(qualifier.TEMPLATES)-{'greeting'})
            self.assertEqual(observed['originalInvocations'], 27)
            self.assertEqual(len(observed['companions']), 4)

    def test_rehashed_normal_receipt_cannot_hide_foreign_source_native_or_signer_payload(self):
        for changed in ('source', 'native', 'package', 'package-path', 'component', 'node', 'marker', 'failed'):
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                record = ordinary(root)
                directory = root/'builds/word-count'
                if changed == 'source':
                    replace_json(root/'source-inputs.json', {'source': 'foreign'})
                    record['sourceIdentityDigest'] = file_identity(root/'source-inputs.json')['sha256']
                elif changed == 'native':
                    (root/'native-binaries/latentd').write_bytes(b'foreign native host')
                elif changed == 'package':
                    (directory/'package-source.json').write_bytes(b'{"layers":[]}\n')
                elif changed == 'package-path':
                    replace_json(directory/'package-source.json', {'layers': [{'source': '../outside'}]})
                elif changed == 'component':
                    (directory/'component.wasm').write_bytes(b'foreign component')
                elif changed == 'node':
                    replace_json(root/'node/workflow.json', {'status': 'failed'})
                elif changed == 'marker':
                    replace_json(directory/'BUILD-COMPLETE.json', {})
                else: record['status'] = 'failed'
                replace_json(root/'qualification.json', record)
                with patch.object(qualifier, 'current_inputs', return_value={'source': 'original normal qualification'}):
                    with self.assertRaises((RuntimeError, ValueError, InstallError)):
                        qualifier.prepared(root, 'rust')

    def test_builder_uses_normal_default_runtime_and_only_rust_dotnet_offline_flags(self):
        binaries = {name: Path(name.replace('/', '-')) for name in qualifier.PRODUCTS}
        modules = {'rust': 'tools.rust_capsule_build', 'c': 'tools.c_capsule_build',
            'go': 'tools.go_capsule_build', 'java': 'tools.java_capsule_build', 'dotnet': 'tools.dotnet_guest.build'}
        for language, module in modules.items():
            with self.subTest(language=language), patch(module+'.build', return_value=Path('compiled')) as build, \
                    patch.object(qualifier.shutil, 'which', return_value=__file__):
                result = qualifier.build_component(language, Path('application'), Path('output'), binaries,
                    tools=Path('dotnet-tools'), wasi_sdk=Path('wasi-sdk'))
                self.assertEqual(result, Path('compiled'))
                self.assertEqual(build.call_args.args[:5], (Path('application'), Path('output'),
                    binaries['examples/capsule_contracts'], binaries['examples/package'], qualifier.REPOSITORY))
                self.assertNotIn('runtime_profile', build.call_args.kwargs)
                if language in ('rust', 'dotnet'): self.assertTrue(build.call_args.kwargs['offline'])
                if language == 'java': self.assertEqual(build.call_args.args[5], Path('wasi-sdk'))

    def test_public_bundle_contains_observed_products_and_no_keys_caches_or_original_library_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = parent/'normal';root.mkdir()
            ordinary(root)
            (root/'private-signing-key.pem').write_bytes(b'not a real key; excluded')
            (root/'compiler-cache').mkdir()
            (root/'compiler-cache/private-library.txt').write_bytes(b'excluded original source')
            with patch.object(qualifier, 'current_inputs', return_value={'source': 'original normal qualification'}):
                result = qualifier.bundle(root, 'rust', parent/'bundle')
            selected = {path.relative_to(parent/'bundle').as_posix() for path in (parent/'bundle').rglob('*') if path.is_file()}
            self.assertEqual(result['status'], 'passed')
            self.assertFalse(result['privateCredentialsExported'])
            self.assertFalse(result['compilerCachesExported'])
            self.assertFalse(any('private' in name or 'cache' in name for name in selected))
            self.assertEqual(sum(name.startswith('native-binaries/') for name in selected), 5)

    def test_owning_rust_child_reuses_normal_products_without_another_native_build_or_longer_parent(self):
        from tools.ci_lane_inventory import workflow_model
        jobs = workflow_model((qualifier.ROOT/'.github/workflows/rust-capsule-authoring.yml').read_text(encoding='utf-8'))['jobs']
        selected = jobs['scratch-refusals']
        self.assertEqual(selected['needs'], 'authoring')
        self.assertEqual(selected['timeout-minutes'], 20)
        self.assertEqual(jobs['authoring']['timeout-minutes'], 35)
        commands = '\n'.join(step.get('run', '') for step in selected['steps'])
        self.assertIn('tools/qualify_sdk_scratch.py --language rust', commands)
        self.assertIn('--native-qualification "$RUNNER_TEMP/rust-scratch-prepared"', commands)
        self.assertNotIn('cargo build', commands)
        self.assertNotIn('cargo test', commands)
        export = next(step['run'] for step in jobs['authoring']['steps']
            if step.get('name') == 'Export exact normal public prerequisites for the separate scratch packet')
        self.assertIn('--export-bundle --language rust', export)
        self.assertIn('--native-qualification "$RUNNER_TEMP/rust-capsule-authoring"', export)
        self.assertNotIn('rust-capsule-dependencies', export)
        download = next(step['with'] for step in selected['steps'] if 'download-artifact@' in step.get('uses', ''))
        self.assertEqual(download['name'], 'rust-scratch-prepared-${{ github.sha }}')

    def test_existing_compatibility_report_keeps_unknown_and_trap_separate_from_actual_unsupported(self):
        from tools import guest_compatibility as compatibility
        from tools.sdk_scratch_probe import refusal
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = compatibility.report('rust', digest(b'actual source'), digest(b'signed component'),
                'lsf-host-abi-phase3-v4', [], [compatibility.finding('lifecycle-unproven', 'retirement', 'not-evaluated', owner_issue=736)])
            write_json(root/'compatibility-report.json', original)
            rows = []
            for mode, category in zip(qualifier.CASES['rust'], ('unsupported', 'not-found', 'unsupported')):
                decoded = [{'ok': 'scratch|rust|io-error|kind='+category+'|fresh=1'}]
                rows.append({'mode': mode, 'observation': refusal('rust', decoded), 'invocation': {
                    'processReaped': True, 'exitCode': 0, 'response': {'outcomeKnown': True}, 'decoded': decoded}})
            node = {'releaseSet': {'releases': [{'name': 'my-greeting', 'componentDigest': original['componentDigest']}]},
                'standardScratchRefusal': {'status': 'passed', 'language': 'rust', 'cases': rows}}
            report = qualifier.execution_report('rust', root, node)
            self.assertEqual([row['classification'] for row in report['findings']],
                ['lifecycle-unproven', 'unsupported-reached', 'unresolved-behavior', 'unsupported-reached', 'unresolved-behavior'])
            self.assertEqual(report['componentDigest'], original['componentDigest'])
            self.assertEqual(report['status'], 'blocked')
            rows[1]['observation']['unsupported'] = True
            with self.assertRaisesRegex(RuntimeError, 'scratch-report-category-recheck'):
                qualifier.execution_report('rust', root, node)
            rows[1]['observation']['unsupported'] = False
            node['releaseSet']['releases'][0]['componentDigest'] = digest(b'foreign component')
            with self.assertRaisesRegex(RuntimeError, 'scratch-report-signed-component-mismatch'):
                qualifier.execution_report('rust', root, node)


if __name__ == '__main__': unittest.main()
