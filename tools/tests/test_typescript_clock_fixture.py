"""Ordinary library value controls; captured compiler/signed evidence is separate."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from tools import typescript_standard_clock_fixture as fixture
from tools.rust_capsule_project import ROOT, snapshot
from tools.typescript_guest.project import create


class ClockFixture(unittest.TestCase):
    def test_closed_probe_keeps_original_world_sdk_and_body_and_covers_each_now_read(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = snapshot(create(root/'original', 'word-count'))
            current = snapshot(fixture.closed_project(root/'closed'))
            self.assertEqual(current['wit/world.wit'], original['wit/world.wit'])
            self.assertEqual(current['sdk-lock.json'], original['sdk-lock.json'])
            self.assertEqual(current['capsule-project.json'], original['capsule-project.json'])
            source = current['src/main.ts'].decode()
            for mode in ('now', 'function', 'function-args', 'construct', 'monotonic', 'origin'):
                self.assertIn("case '"+mode+"':", source)
            self.assertIn('unsupported:standard-clock-without-approved-profile', source)
            self.assertIn('closed-explicit-Date-changed', source)
            original_body = original['src/main.ts'].decode().split('  count(text) {', 1)[1]
            self.assertTrue(source.endswith(original_body))

    def test_actual_outside_library_uses_standard_apis_resources_and_fresh_module_state(self):
        node = shutil.which('node')
        self.assertIsNotNone(node)
        original = fixture.LIBRARY
        self.assertEqual(original.count("import {text, bytes} from 'outside-clock-data';"), 1)
        self.assertEqual(original.count('export function clockCase(mode)'), 1)
        body = original.replace("import {text, bytes} from 'outside-clock-data';", 'const {text,bytes}=globalThis.fixtureData;', 1)
        body = body.replace('export function clockCase(mode)', 'function clockCase(mode)', 1)
        prefix = "import assert from 'node:assert/strict';import vm from 'node:vm';\n"
        prefix += 'import {installApplicationClocks} from '+json.dumps((ROOT/'tools/typescript_guest/clock_app.mjs').as_uri())+';\n'
        code = prefix+'const original='+json.dumps(body)+';const globals='+json.dumps(
            (ROOT/'sdk/typescript-guest/activation/clock_globals.js').read_bytes().decode())+';\n'
        code += 'const data='+json.dumps({'text': fixture.TEXT, 'bytes': list(fixture.BINARY)})+';\n'
        code += """
function realm() {
 const context=vm.createContext({performance:{},fixtureData:data});
 const target=vm.runInContext('globalThis',context);let mono=0,reads=0;
 target.__lsfSelectedClockBridge={wall(){reads++;return 1760000000000;},
  now(){reads++;return mono++/4;},origin(){reads++;return 1760000000000;}};
 vm.runInContext(globals,context);installApplicationClocks(true,()=>false,target);
 vm.runInContext(original,context);assert.equal(reads,0);return {context,readCount:()=>reads};
}
for(const mode of ['entry','wall','explicit','monotonic','repeated','fresh']) {
 const {context,readCount}=realm();const result=vm.runInContext('clockCase('+JSON.stringify(mode)+')',context);
 assert.equal(result,'clock:'+mode+'|clock|Gr\\u00fc\\u00dfe|binary=00ff4180|fresh=1');
 assert.equal(readCount()>0,!['entry','explicit'].includes(mode));
 assert.throws(()=>vm.runInContext('clockCase("fresh")',context),/clock-state-reused/);
}
assert.throws(()=>vm.runInContext('clockCase("trap")',realm().context),/ordinary-clock-fixture-trap/);
"""
        result = subprocess.run([node, '--input-type=module', '-e', code], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
