"""Reproduce the packaged reader failure before preparing its exact closure repair."""
from pathlib import Path
import json
import os
import subprocess
import sys

ROOT = Path.cwd()
HEAD = 'f1dd3bc1c6ed68d2b4e5a0ed0c75d8bcf3e7f588'
def git(*args):
    return subprocess.check_output(['git', *args], text=True, timeout=120).strip()
def replace(path, old, new):
    target = ROOT / path
    text = target.read_text()
    assert text.count(old) == 1, (path, old)
    target.write_text(text.replace(old, new), newline='\n')
assert git('rev-parse', 'HEAD') == HEAD
assert not git('status', '--porcelain')
tests = 'tools/tests/test_dev_tools.py'
method = '''
    @unittest.skipUnless(sys.platform == "linux", "The packaged node helper runs on Linux")
    def test_packaged_helper_reads_compatibility_context_without_checkout_imports(self):
        import subprocess
        import textwrap
        import zipfile
        from tools.build_dev_frontend import helper

        script = """
            import copy
            from pathlib import Path
            import sys
            sys.path.insert(0, sys.argv[1])
            from tools import guest_compatibility as compatibility
            from tools import guest_compatibility_context as context
            from tools import guest_compatibility_outcomes as outcomes
            from tools.dev_workflow import paths
            from tools.dev_workflow.common import digest, encode

            assert outcomes.__file__.startswith(sys.argv[1] + '/')
            root = Path(sys.argv[2])
            original_source = b'compiler-owned source inventory'
            receipt = {'source': digest(b'frontend source'),
                       'artifacts': {'component': digest(b'component')}}
            descriptor = {'artifacts': {'component': 'out/component.wasm'}}
            for language in ('rust', 'c', 'java', 'dotnet', 'go', 'typescript'):
                source = root / language
                paths.new_directory(source)
                output = source / 'out'
                paths.new_directory(output)
                report = compatibility.report(language, digest(original_source),
                    receipt['artifacts']['component'], 'lsf-host-abi-phase3-v4', [], [])
                selected = context.create(report, [], {'state': 'absent'})
                for name, raw in (('source-inputs.json', original_source),
                                  ('compatibility-report.json', encode(report)),
                                  ('compatibility-context.json', encode(selected))):
                    paths.write_new(output / name, raw)
                # This is the original post-deployment reader, not a mocked
                # import or a checkout module satisfying the archive by accident.
                collector = outcomes.from_build(source, descriptor, receipt)
                assert collector.context_state == 'observed'
                original = {'category': 'platform-failure', 'outcomeKnown': False,
                            'error': {'code': 'unavailable'}, 'data': {}}
                unchanged = copy.deepcopy(original)
                collector.observe('original', original, True)
                observed = collector.snapshot()
                assert original == unchanged
                assert observed['cases'][0]['outcomeKnown'] is False
                assert (observed['authority'], observed['workerDrain'], observed['retrySafety']) == (
                    'none', 'unproven', 'unknown')
                (output / 'compatibility-context.json').write_bytes(b'{}')
                assert outcomes.from_build(source, descriptor, receipt).context_state == 'invalid-present'
                (output / 'compatibility-context.json').unlink()
                assert outcomes.from_build(source, descriptor, receipt).context_state == 'absent'

            # Exercise the lazy TypeScript closure too. Do not bundle an entire
            # compiler distribution merely to read its closed module receipt.
            from tools import guest_compatibility_context_build as materials
            from tools.typescript_guest import buffer_profile
            assert materials.__file__.startswith(sys.argv[1] + '/')
            assert buffer_profile.__file__.startswith(sys.argv[1] + '/')
            backend = {'digest': digest(b'backend'), 'size': 7}
            declaration = {'digest': digest(b'declaration'), 'size': 11}
            recipe = encode({buffer_profile.BACKEND: backend,
                             buffer_profile.DECLARATION: declaration})
            captured = encode({'vendor/lsf/' + buffer_profile.DECLARATION: declaration})
            selection = buffer_profile.check_selection({'standardBufferModules': ['node:buffer'],
                'standardBufferProfile': buffer_profile.PROFILE,
                'standardBufferBackendDigest': backend['digest']}, backend['digest'])
            result = materials.typescript_buffer_materials(encode(selection), recipe, captured)
            assert len(result) == 3 and all(row['profile'] == buffer_profile.PROFILE for row in result)
            selection['authority'] = 'invented'
            try:
                materials.typescript_buffer_materials(encode(selection), recipe, captured)
            except ValueError:
                pass
            else:
                raise AssertionError('changed owner receipt was accepted')
            assert materials.java_compiler_materials({}, 'fixture', digest(recipe)) == []
            print('packaged-compatibility-ok')
        """
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / 'helper.pyz'
            helper(archive)
            with zipfile.ZipFile(archive) as packed:
                self.assertNotIn('tools/typescript_guest/node_buffer.mjs', packed.namelist())
                self.assertNotIn('tools/typescript_capsule.py', packed.namelist())
            selected = root / 'inputs'
            selected.mkdir(mode=0o700)
            # -I ignores PYTHONPATH, user site packages and the checkout working
            # directory; -S also excludes site packages. Only the zip + stdlib
            # may satisfy these imports in the real child interpreter.
            completed = subprocess.run([sys.executable, '-I', '-S', '-c', textwrap.dedent(script),
                str(archive), str(selected)], cwd=root, capture_output=True, timeout=30)
            self.assertEqual(completed.returncode, 0, completed.stderr.decode(errors='replace'))
            self.assertEqual(completed.stdout, b'packaged-compatibility-ok\\n')
            self.assertEqual(completed.stderr, b'')

'''
replace(tests, 'class FrontendDistribution(unittest.TestCase):\n',
        'class FrontendDistribution(unittest.TestCase):\n' + method)
command = [sys.executable, '-m', 'unittest',
           'tools.tests.test_dev_tools.FrontendDistribution.test_packaged_helper_reads_compatibility_context_without_checkout_imports']
negative = subprocess.run(command, cwd=ROOT, capture_output=True, timeout=90)
evidence = Path(os.environ['RUNNER_TEMP']) / 'audit-helper'
evidence.mkdir()
(evidence / 'before.log').write_bytes(negative.stdout + negative.stderr)
assert negative.returncode == 1 and b'guest_compatibility_context_build' in negative.stderr, negative.stderr[-8000:]
print('BEFORE: actual helper archive reproduces missing compatibility-context reader', flush=True)
source = 'tools/build_dev_frontend.py'
replace(source, '"guest_compatibility_outcomes", "guest_runtime_receipts",',
        '"guest_compatibility_outcomes", "guest_compatibility_context_build", "guest_emitted_code", "guest_runtime_receipts",')
replace(source, '    for name, raw in resource_snapshot if resource_snapshot is not None else preflight_resources():',
        '''    # Outcome readers reuse the compiler owner's pure material validators.
    # Include the finite lazy Buffer reader, not its compiler or JS backend.
    entries["tools/typescript_guest/__init__.py"] = b""
    name = "tools/typescript_guest/buffer_profile.py"
    entries[name] = (ROOT / name).read_bytes()
    for name, raw in resource_snapshot if resource_snapshot is not None else preflight_resources():''')
positive = subprocess.run(command, cwd=ROOT, capture_output=True, timeout=90)
(evidence / 'after.log').write_bytes(positive.stdout + positive.stderr)
assert positive.returncode == 0, positive.stderr[-8000:]
print('AFTER: six language contexts, absent/invalid context, original uncertainty and lazy Buffer validation pass outside checkout', flush=True)
sys.path.insert(0, str(ROOT))
from tools import ci_contracts
for kind, path, reason in (
    ('owner', source, 'Explicitly package the existing pure compatibility material reader, its emitted-code dependency and the finite TypeScript Buffer profile reader. Preserve the curated bundle, every prior resource, deterministic encoding, byte identities, authority checks and existing build/smoke commands; do not bundle compilers or add fallback imports.'),
    ('python', tests, 'Preserve all existing cases, fixtures and skip guards. Add a Linux-helper archive regression run with isolated Python outside the checkout for six languages, valid/absent/invalid contexts, original uncertain results and the lazy Buffer reader. The new case runs only on the helper target platform; no old test is skipped.'),
):
    output = ROOT / 'target/ci/proposals/audit-helper' / kind
    proposed = ci_contracts.propose(ROOT, kind, path, None, output, reason)
    destination = ROOT / ci_contracts.DIRECTORY / proposed.relative_to(output)
    destination.write_bytes(proposed.read_bytes())
allowed = {source, tests, 'tools/ci/contracts/owners/tools/build_dev_frontend.py.json',
           'tools/ci/contracts/python/test_dev_tools.py.json'}
assert set(git('diff', '--name-only').splitlines()) == allowed
assert not git('ls-files', '--others', '--exclude-standard')
