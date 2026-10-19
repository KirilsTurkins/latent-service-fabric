"""Source/native-JavaScript controls only; no signed retirement claim."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from tools import typescript_runtime_retirement_fixture as fixture
from tools.rust_capsule_project import snapshot
from tools.typescript_guest.project import create


class RetirementFixture(unittest.TestCase):
    def test_pending_export_is_declared_async_and_original_sdk_and_limits_are_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = snapshot(create(root/'original', 'greeting', runtime_profile=fixture.CLOCK_PROFILE))
            selected = snapshot(fixture.project(root/'selected'))
            self.assertEqual(selected['sdk-lock.json'], original['sdk-lock.json'])
            self.assertEqual({n: raw for n, raw in selected.items() if n.startswith('vendor/')},
                             {n: raw for n, raw in original.items() if n.startswith('vendor/')})
            self.assertEqual(json.loads(selected['capsule-project.json'])['limits'],
                             json.loads(original['capsule-project.json'])['limits'])
            self.assertIn(b'run: async func(mode: u32)', selected['wit/world.wit'])
            self.assertEqual(selected['src/main.ts'], fixture.MAIN)
            self.assertNotIn(b'latent:runtime', fixture.MAIN)
            self.assertNotIn(b'shutdown', fixture.LIBRARY)

    def test_actual_library_has_genuinely_pending_promise_clear_and_distinguishable_accepted_callback_error(self):
        node = shutil.which('node'); self.assertIsNotNone(node)
        body = fixture.LIBRARY.decode().replace('export async function lifecycle(', 'async function lifecycle(', 1)
        prefix = "import assert from 'node:assert/strict';import vm from 'node:vm';import {inspect,types} from 'node:util';\n"
        code = prefix+'const source='+json.dumps(body)+';\n'+r'''
function realm() {
 const timers=new Map();let next=1;
 const context=vm.createContext({setTimeout(callback,millis){const id=next++;timers.set(id,{callback,millis});return id;},
  clearTimeout(id){assert.ok(timers.delete(id));}});
 vm.runInContext(source,context);return {context,timers};
}
const held=realm(),pending=vm.runInContext('lifecycle(0)',held.context);
assert.ok(types.isPromise(pending));assert.match(inspect(pending),/<pending>/);
assert.equal(held.timers.size,1);const timer=[...held.timers.values()][0];assert.equal(timer.millis,3600000);
timer.callback();assert.equal(await pending,42);
await assert.rejects(vm.runInContext('lifecycle(1)',held.context),/module-state-reused/);
const clear=realm();assert.equal(await vm.runInContext('lifecycle(3)',clear.context),42);assert.equal(clear.timers.size,0);
const late=realm();assert.equal(await vm.runInContext('lifecycle(4)',late.context),42);assert.equal(late.timers.size,1);
assert.throws(()=>[...late.timers.values()][0].callback(),/accepted-callback-must-not-disappear/);
const trap=realm();await assert.rejects(vm.runInContext('lifecycle(2)',trap.context),/root-trap-with-accepted-timer/);
assert.equal(trap.timers.size,1);assert.equal(await vm.runInContext('lifecycle(1)',realm().context),42);
'''
        result = subprocess.run([node, '--input-type=module', '-e', code], capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8'))

    def test_invalid_outside_parent_refuses_before_writing_or_running_native_authoring(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);app = fixture.project(root/'app');(root/'other').mkdir()
            before = snapshot(app)
            with self.assertRaisesRegex(RuntimeError, 'owned-outside-source'):
                fixture.capture(app, root/'other/source')
            self.assertFalse((root/'other/source').exists())
            self.assertEqual(snapshot(app), before)


if __name__ == '__main__': unittest.main()
