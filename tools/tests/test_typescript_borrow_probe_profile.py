"""Host-only guards for the owned probe selection; no runtime qualification."""
import subprocess
import shutil
import tempfile
import unittest
from pathlib import Path
from tools.rust_capsule_project import ROOT
from tools.typescript_guest import borrow_probe_profile as probe
from tools.typescript_guest.runtime_profile import IMPORT_PROFILE


class BorrowProbeProfileTests(unittest.TestCase):
    def prepare(self, work):
        for name, source in probe.INPUTS.items():
            path = work / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((ROOT / source).read_bytes())

    def test_exact_owned_graph_admitted_and_changed_or_extra_inputs_refuse(self):
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            self.prepare(work)
            self.assertTrue(probe.validate(probe.PROFILE, work, probe.WORLD, IMPORT_PROFILE, None))
            (work / 'src/main.ts').write_text('changed')
            with self.assertRaisesRegex(ValueError, 'source-changed'):
                probe.validate(probe.PROFILE, work, probe.WORLD, IMPORT_PROFILE, None)
            self.prepare(work)
            (work / 'src/extra.ts').write_text('export const extra=1;')
            with self.assertRaisesRegex(ValueError, 'exact-source-graph'):
                probe.validate(probe.PROFILE, work, probe.WORLD, IMPORT_PROFILE, None)

    def test_default_is_lazy_and_wrong_profile_or_modules_refuse(self):
        absent = Path('absent-probe-work')
        self.assertFalse(probe.validate(None, absent, 'other', 'other', None))
        for arguments in [('unknown', probe.WORLD, IMPORT_PROFILE, None),
                          (probe.PROFILE, 'other', IMPORT_PROFILE, None),
                          (probe.PROFILE, probe.WORLD, 'other', None),
                          (probe.PROFILE, probe.WORLD, IMPORT_PROFILE, {})]:
            selection, world, runtime, modules = arguments
            with self.assertRaisesRegex(ValueError, 'profile-required'):
                probe.validate(selection, absent, world, runtime, modules)

    def test_generated_read_shape_is_exact_before_private_declaration_staging(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            path = directory / 'gate.d.ts'
            original = ('/** @module Interface ' + probe.GATE + ' **/\n'
                        'export function read(source: Connection, maximumBytes: number, '
                        'timeoutMillis: number | undefined): Promise<Chunk | undefined>;\n')
            path.write_text(original)
            probe.declarations(directory)
            private = directory / 'borrow-probe-private.d.ts'
            self.assertEqual(private.read_bytes(), (ROOT / (probe.PREFIX + 'private.d.ts')).read_bytes())
            private.unlink()
            path.write_text(original.replace('Promise<Chunk | undefined>', 'Chunk | undefined'))
            with self.assertRaisesRegex(ValueError, 'generated-read-shape-drift'):
                probe.declarations(directory)
            self.assertFalse(private.exists())

    def test_private_builtin_configuration_refuses_unselected_or_changed_runtime(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('Node required for host-only module guard')
        module = (ROOT / 'tools/typescript_guest/borrow_probe.mjs').as_uri()
        script = """
import assert from 'node:assert/strict';
const {borrowProbeBindings:binding,borrowProbeConfiguration:config,borrowProbeProfile:profile}=await import(MODULE);
assert.equal(binding('unaltered',()=>{throw Error('must not parse');},undefined),'unaltered');
const imports=new Set(['latent:network/streams@0.1.0','tests:typescript-import-borrow-gate/streams@1.0.0','tests:typescript-import-borrow-gate/diagnostic@1.0.0']);
assert.equal(config({},imports),false);
assert.equal(config({borrowProbeProfile:profile,runtimeProfile:'spidermonkey-activation-promises-clocks-imports-v1'},imports),true);
for(const value of [{borrowProbeProfile:'other'}, {borrowProbeProfile:profile,runtimeProfile:'other'}]) assert.throws(()=>config(value,imports));
assert.throws(()=>config({borrowProbeProfile:profile,runtimeProfile:'spidermonkey-activation-promises-clocks-imports-v1'},new Set()));
assert.throws(()=>config({borrowProbeProfile:profile,runtimeProfile:'spidermonkey-activation-promises-clocks-imports-v1'},new Set([...imports,'other:extra/api@1.0.0'])));
assert.throws(()=>binding('unaltered',()=>{},'other'));
""".replace('MODULE', repr(module))
        subprocess.run([node, '--input-type=module', '-e', script], check=True, timeout=20)
