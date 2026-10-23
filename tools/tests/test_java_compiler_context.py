"""Selected compiler receipt controls; no compiler/guest execution evidence."""
import copy
import unittest

from tools import guest_compatibility_context as context
from tools import guest_compatibility_context_build as builder
from tools import guest_compatibility_outcomes as outcomes
from tools.dev_workflow.common import DevError, digest, encode
from tools.tests import test_guest_compatibility_context as fixtures


def compiler_patch():
    """Explicit receipt protocol fixture, not an executed compiler claim."""
    names = ('originalJarSha256', 'replacementJarSha256', 'upstreamSourceSha256',
        'correctedSourceSha256', 'upstreamTypeSourceSha256', 'correctedTypeSourceSha256',
        'upstreamAsyncFinderSourceSha256', 'correctedAsyncFinderSourceSha256')
    value = {name: digest(name.encode())[7:] for name in names}
    value.update(schemaVersion='latent.java.coroutine-compiler-patch.v1',
        replacedClasses={'Compiler.class': {'originalSha256': 'a' * 64, 'replacementSha256': 'b' * 64}},
        loadedCompiler={'schemaVersion': 'latent.java.coroutine-compiler-load.v1',
            'selectedOwnedReplacement': True, 'replacementJarSha256': value['replacementJarSha256'],
            'loadedJarSha256': value['replacementJarSha256'], 'codeSourceKind': 'owned-replacement',
            'loadedClasses': {'Compiler.class': 'b' * 64}})
    return value


class JavaCompilerContext(unittest.TestCase):
    def setUp(self):
        fixture = fixtures.BuildContext()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.output, self.original = fixture.output, fixture.original
        self.receipt, self.finish = fixture.receipt, fixture.finish

    def test_java_compiler_original_selected_and_source_pairs_are_presented_without_support_claim(self):
        self.receipt('runtime-profile.json', 'java-runtime-profile', {'profile': 'teavm-activation-fibers-v1'})
        selected = compiler_patch()
        selected['privateDiagnostic'] = 'https://credential:private@host/secret'
        self.receipt('bindings.json', 'generated-bindings', {'coroutineCompiler': selected})
        value = self.finish()
        rows = {row['name']: row for row in value['materials'] if row['kind'] == 'patch'}
        self.assertEqual(set(rows), {'java-teavm-coroutine-compiler', 'java-teavm-coroutine-source',
            'java-teavm-array-root-source', 'java-teavm-monitor-source'})
        jar = rows['java-teavm-coroutine-compiler']
        self.assertEqual(jar['originalDigest'], 'sha256:' + selected['originalJarSha256'])
        self.assertEqual(jar['digest'], 'sha256:' + selected['replacementJarSha256'])
        self.assertEqual(rows['java-teavm-monitor-source']['digest'],
            'sha256:' + selected['correctedAsyncFinderSourceSha256'])
        self.assertNotIn(jar['transformDigest'], {jar['digest'], jar['originalDigest']})
        self.assertNotIn('credential', encode(value).decode())
        self.assertNotIn('private@host', context.present(value))
        self.assertIn(jar['originalDigest'], context.present(value))
        self.assertEqual((value['qualification'], value['workerDrain'], value['authority']),
            ('unknown', 'unproven', 'none'))
        self.assertEqual((self.output / 'compatibility-report.json').read_bytes(), self.original)

    def test_java_compiler_load_and_original_source_identity_mismatches_are_refused(self):
        for change in ('jar', 'classes', 'selected', 'source', 'missing-source', 'schema'):
            selected = compiler_patch()
            if change == 'jar': selected['loadedCompiler']['loadedJarSha256'] = 'c' * 64
            elif change == 'classes': selected['loadedCompiler']['loadedClasses'] = {}
            elif change == 'selected': selected['loadedCompiler']['selectedOwnedReplacement'] = 1
            elif change == 'source': selected['correctedTypeSourceSha256'] = 'not-a-digest'
            elif change == 'missing-source': del selected['upstreamSourceSha256']
            else: selected['schemaVersion'] = 'future-schema'
            with self.subTest(change=change), self.assertRaises(DevError):
                builder.java_compiler_materials({'coroutineCompiler': selected},
                    'teavm-activation-fibers-v1', digest(b'recipe'))

    def test_java_compiler_projection_requires_bound_bindings_and_preserves_base_builds(self):
        self.receipt('bindings.json', 'generated-bindings', {'ordinary': 'base-build'})
        value = self.finish()
        self.assertFalse(any(row['kind'] == 'patch' for row in value['materials']))
        (self.output / 'bindings.json').write_bytes(encode({'coroutineCompiler': compiler_patch()}))
        with self.assertRaisesRegex(DevError, 'stale-or-unbound-receipt'): self.finish()

    def test_java_compiler_context_is_rechecked_against_actual_binding_and_recipe_sidecars(self):
        self.receipt('runtime-profile.json', 'java-runtime-profile', {'profile': 'teavm-activation-fibers-v1'})
        self.receipt('bindings.json', 'generated-bindings', {'coroutineCompiler': compiler_patch()})
        value = self.finish()
        (self.output / 'source-inputs.json').write_bytes(fixtures.SOURCE)
        (self.output / 'recipe-inputs.json').write_bytes(b'recipe')
        descriptor = {'artifacts': {'component': 'component.wasm'}}
        receipt = {'source': digest(b'frontend'), 'artifacts': {'component': digest(fixtures.COMPONENT)}}
        def observed():
            return outcomes.from_build(self.output, descriptor, receipt).context_state
        self.assertEqual(observed(), 'observed')
        for name in ('bindings.json', 'recipe-inputs.json'):
            original = (self.output / name).read_bytes()
            (self.output / name).write_bytes(b'changed')
            self.assertEqual(observed(), 'invalid-present')
            (self.output / name).write_bytes(original)
        detached = copy.deepcopy(value)
        next(row for row in detached['materials'] if row['name'] == 'java-teavm-monitor-source')['digest'] = digest(b'other')
        detached['identity'] = digest(encode({key: row for key, row in detached.items() if key != 'identity'}))
        (self.output / 'compatibility-context.json').write_bytes(encode(detached))
        self.assertEqual(observed(), 'invalid-present')
        detached['materials'] = [row for row in detached['materials']
            if row['name'] != 'java-teavm-coroutine-compiler']
        detached['identity'] = digest(encode({key: row for key, row in detached.items() if key != 'identity'}))
        (self.output / 'compatibility-context.json').write_bytes(encode(detached))
        self.assertEqual(observed(), 'invalid-present')
        empty_bindings = encode({'ordinary': 'base-build'})
        (self.output / 'bindings.json').write_bytes(empty_bindings)
        detached = copy.deepcopy(value)
        next(row for row in detached['materials'] if row['name'] == 'generated-bindings')['digest'] = digest(empty_bindings)
        detached['identity'] = digest(encode({key: row for key, row in detached.items() if key != 'identity'}))
        (self.output / 'compatibility-context.json').write_bytes(encode(detached))
        self.assertEqual(observed(), 'invalid-present')
