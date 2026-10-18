"""Generated waiters preserve real import suspension without idle pending work."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class TypeScriptAsyncWaiterTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "requires Node")
    def test_task_exited_before_first_slot_is_refused_without_granting_entry(self):
        source = r"""
import assert from 'node:assert/strict';
import {writeFile} from 'node:fs/promises';
import {retireGeneratedTaskSlots} from './async_waiters.mjs';
const generated = `class Slots {
  #nextTaskPromise = Promise.resolve(true);
  #nextTaskQueue = [];
  retained() { return this.#nextTaskQueue.length; }
  current() { return this.#nextTaskPromise; }
  async nextTaskExecutionSlot({task}) {
    const placeholder = {
      completed: false,
      task,
      promise: task.exitPromise().then(() => {
        placeholder.completed = true;
      }),
    };
    this.#nextTaskQueue.push(placeholder);
    while (true) {
      await this.#nextTaskPromise;
      const next = this.#nextTaskQueue.find(entry => !entry.completed);
      if (next === undefined || next === placeholder) {
        this.#nextTaskPromise = next.promise;
        break;
      }
    }
  }
};`;
await writeFile(new URL('./generated.mjs', import.meta.url),
  retireGeneratedTaskSlots(generated) + '\nexport default Slots;\n');
const {default:Slots} = await import('./generated.mjs');
const slots = new Slots();
let entered = false;
await assert.rejects(slots.nextTaskExecutionSlot({task:{exitPromise:() => Promise.resolve()}})
  .then(() => {entered = true;}), /^Error: selected-runtime-task-exited-before-slot$/);
assert.equal(entered, false);
assert.equal(slots.retained(), 0);
assert.equal(slots.current(), null);
const anchor = '      await this.#nextTaskPromise;\n';
assert.throws(() => retireGeneratedTaskSlots(generated.replace(anchor, '')), /shape-drift/);
assert.throws(() => retireGeneratedTaskSlots(generated + anchor), /shape-drift/);
"""
        with tempfile.TemporaryDirectory() as owned:
            root = Path(owned)
            (root / "async_waiters.mjs").write_bytes(
                (ROOT / "tools/typescript_guest/async_waiters.mjs").read_bytes()
            )
            (root / "test.mjs").write_text(source, encoding="utf-8")
            result = subprocess.run(
                [shutil.which("node"), str(root / "test.mjs")],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(shutil.which("node"), "requires Node")
    def test_exited_middle_waiter_refuses_before_live_successor_exits(self):
        source = r"""
import assert from 'node:assert/strict';
import {writeFile} from 'node:fs/promises';
import {retireGeneratedTaskSlots} from './async_waiters.mjs';
const generated = `class Slots {
  #nextTaskPromise = Promise.resolve(true);
  #nextTaskQueue = [];
  retained() { return this.#nextTaskQueue.length; }
  current() { return this.#nextTaskPromise; }
  async nextTaskExecutionSlot({task}) {
    const placeholder = {
      completed: false,
      task,
      promise: task.exitPromise().then(() => {
        placeholder.completed = true;
      }),
    };
    this.#nextTaskQueue.push(placeholder);
    while (true) {
      await this.#nextTaskPromise;
      const next = this.#nextTaskQueue.find(entry => !entry.completed);
      if (next === undefined || next === placeholder) {
        this.#nextTaskPromise = next.promise;
        break;
      }
    }
  }
};`;
await writeFile(new URL('./generated.mjs', import.meta.url),
  retireGeneratedTaskSlots(generated) + '\nexport default Slots;\n');
const {default:Slots} = await import('./generated.mjs');
const slots = new Slots();
const first = Promise.withResolvers(), middle = Promise.withResolvers(), last = Promise.withResolvers();
await slots.nextTaskExecutionSlot({task:{exitPromise:() => first.promise}});
const order = [];
let middleFailure, middleEntered = false;
const waitMiddle = slots.nextTaskExecutionSlot({task:{exitPromise:() => middle.promise}})
  .then(() => {middleEntered = true;}, error => {middleFailure = error; order.push('retired');});
const waitLast = slots.nextTaskExecutionSlot({task:{exitPromise:() => last.promise}})
  .then(() => order.push('last'));
middle.resolve();
await Promise.resolve();
assert.equal(slots.retained(), 2);
assert.equal(middleFailure, undefined); // Original current-task wait still owns this continuation.
first.resolve();
await waitLast;
assert.equal(middleFailure?.message, 'selected-runtime-task-exited-before-slot');
await waitMiddle;
assert.equal(middleEntered, false);
assert.deepEqual(order, ['retired', 'last']);
assert.equal(slots.retained(), 1);
assert.notEqual(slots.current(), null);
last.resolve();
await Promise.resolve();
await Promise.resolve();
assert.equal(slots.retained(), 0);
assert.equal(slots.current(), null);
"""
        with tempfile.TemporaryDirectory() as owned:
            root = Path(owned)
            (root / "async_waiters.mjs").write_bytes(
                (ROOT / "tools/typescript_guest/async_waiters.mjs").read_bytes()
            )
            (root / "test.mjs").write_text(source, encoding="utf-8")
            result = subprocess.run(
                [shutil.which("node"), str(root / "test.mjs")],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(shutil.which("node"), "requires Node")
    def test_actual_async_imports_use_application_promises_and_preserve_resources(self):
        source = r"""
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {applicationRealmImportPromises} from './async_waiters.mjs';
const app = vm.createContext({});
const ApplicationPromise = vm.runInContext('Promise', app);
let exports;
const initializer = vm.createContext({
  contentGlobal: {Promise: ApplicationPromise, __lsfAsyncImportBridge: {}},
  defineBuiltinModule(name, values) { assert.equal(name, 'fixture'); exports = values; }
});
const original = `const __lsfImports = contentGlobal.__lsfAsyncImportBridge;
let calls = 0;
const reason = {original: true};
async function call(value) { calls++; await Promise.resolve(); return value; }
async function reject() { throw reason; }
function synchronous() { return 42; }
class Resource {
  constructor() { this.value = 40; }
  async read(extra) { return this.value + extra; }
  static async create() { return new this(); }
}
globalThis.originals = {call, reject, synchronous, Resource, reason};
defineBuiltinModule('fixture', {call, reject, synchronous, Resource});`;
vm.runInContext(applicationRealmImportPromises(original), initializer);
const pending = exports.call(42);
assert(pending instanceof ApplicationPromise);
assert(!(pending instanceof Promise));
assert.equal(exports.call.name, initializer.originals.call.name);
assert.equal(exports.call.length, initializer.originals.call.length);
assert.throws(() => new exports.call(), TypeError);
let settled = false;
pending.then(() => settled = true);
assert.equal(settled, false);
assert.equal(await pending, 42);
assert.equal(vm.runInContext('calls', initializer), 1);
const rejected = exports.reject();
assert(rejected instanceof ApplicationPromise);
await assert.rejects(rejected, error => error === initializer.originals.reason);
assert.equal(exports.synchronous, initializer.originals.synchronous);
assert.equal(exports.synchronous(), 42);
assert.equal(exports.Resource, initializer.originals.Resource);
const resource = new exports.Resource();
const read = resource.read(2);
assert(read instanceof ApplicationPromise);
assert.equal(await read, 42);
const created = exports.Resource.create();
assert(created instanceof ApplicationPromise);
assert((await created) instanceof exports.Resource);
assert.throws(() => applicationRealmImportPromises(''), /shape-drift/);
assert.throws(() => applicationRealmImportPromises(original + original), /shape-drift/);
"""
        with tempfile.TemporaryDirectory() as owned:
            root = Path(owned)
            (root / "async_waiters.mjs").write_bytes(
                (ROOT / "tools/typescript_guest/async_waiters.mjs").read_bytes()
            )
            (root / "test.mjs").write_text(source, encoding="utf-8")
            result = subprocess.run(
                [shutil.which("node"), str(root / "test.mjs")],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(shutil.which("node"), "requires Node")
    def test_idle_state_actual_shared_wait_and_successive_imports(self):
        source = r"""
import assert from 'node:assert/strict';
import {writeFile} from 'node:fs/promises';
import {lazySyncImportWaiters} from './async_waiters.mjs';
let pending = 0;
let allocated = 0;
function promiseWithResolvers() {
  const result = Promise.withResolvers();
  allocated++;
  pending++;
  result.promise.then(() => pending--);
  return result;
}
const generated = `class ComponentAsyncState {
  #callingAsyncImport = false;
  #syncImportWait = promiseWithResolvers();
  callingSyncImport(value) {
    if (value === undefined) return this.#callingAsyncImport;
    const previous = this.#callingAsyncImport;
    this.#callingAsyncImport = value;
    if (previous && !value) this.#notifySyncImportEnd();
  }
  #notifySyncImportEnd() {
    const existing = this.#syncImportWait;
    this.#syncImportWait = promiseWithResolvers();
    existing.resolve();
  }
  async waitForSyncImportCallEnd() {
    await this.#syncImportWait.promise;
  }
};`;
await writeFile(new URL('./generated.mjs', import.meta.url),
  'export default function create(promiseWithResolvers) {\n' +
  lazySyncImportWaiters(generated) + '\nreturn ComponentAsyncState;\n}');
const {default:create} = await import('./generated.mjs');
const State = create(promiseWithResolvers);
const state = new State();
assert.equal(allocated, 0);
await state.waitForSyncImportCallEnd();
assert.equal(allocated, 0);
state.callingSyncImport(true);
state.callingSyncImport(false);
assert.equal(allocated, 0);
for (let epoch = 1; epoch <= 2; epoch++) {
  state.callingSyncImport(true);
  const order = [];
  const first = state.waitForSyncImportCallEnd().then(() => order.push(1));
  const second = state.waitForSyncImportCallEnd().then(() => order.push(2));
  await Promise.resolve();
  assert.deepEqual(order, []);
  assert.equal(allocated, epoch);
  assert.equal(pending, 1);
  state.callingSyncImport(false);
  await Promise.all([first, second]);
  assert.deepEqual(order, [1, 2]);
  assert.equal(pending, 0);
  assert.equal(allocated, epoch);
}
assert.throws(() => lazySyncImportWaiters(generated + generated), /shape-drift/);
assert.throws(() => lazySyncImportWaiters('class Other {}'), /shape-drift/);
"""
        with tempfile.TemporaryDirectory() as owned:
            root = Path(owned)
            (root / "async_waiters.mjs").write_bytes(
                (ROOT / "tools/typescript_guest/async_waiters.mjs").read_bytes()
            )
            (root / "test.mjs").write_text(source, encoding="utf-8")
            result = subprocess.run(
                [shutil.which("node"), str(root / "test.mjs")],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(shutil.which("node"), "requires Node")
    def test_generated_task_slots_retire_after_exit_without_reordering_waiters(self):
        source = r"""
import assert from 'node:assert/strict';
import {writeFile} from 'node:fs/promises';
import {retireGeneratedTaskSlots} from './async_waiters.mjs';
const generated = `class Slots {
  #nextTaskPromise = Promise.resolve(true);
  #nextTaskQueue = [];
  retained() { return this.#nextTaskQueue.length; }
  current() { return this.#nextTaskPromise; }
  async nextTaskExecutionSlot({task}) {
    const placeholder = {
      completed: false,
      task,
      promise: task.exitPromise().then(() => {
        placeholder.completed = true;
      }),
    };
    this.#nextTaskQueue.push(placeholder);
    while (true) {
      await this.#nextTaskPromise;
      const next = this.#nextTaskQueue.find(entry => !entry.completed);
      if (next === undefined || next === placeholder) {
        this.#nextTaskPromise = next.promise;
        break;
      }
    }
  }
};`;
await writeFile(new URL('./generated.mjs', import.meta.url),
  retireGeneratedTaskSlots(generated) + '\nexport default Slots;\n');
const {default:Slots} = await import('./generated.mjs');
const slots = new Slots();
assert.equal(slots.current(), null);
const first = Promise.withResolvers();
const second = Promise.withResolvers();
const order = [];
const enterFirst = slots.nextTaskExecutionSlot({task:{exitPromise:() => first.promise}}).then(() => order.push(1));
await enterFirst;
const enterSecond = slots.nextTaskExecutionSlot({task:{exitPromise:() => second.promise}}).then(() => order.push(2));
await Promise.resolve();
assert.deepEqual(order, [1]);
assert.equal(slots.retained(), 2);
first.resolve();
await enterSecond;
assert.deepEqual(order, [1, 2]);
assert.equal(slots.retained(), 1);
second.resolve();
await Promise.resolve();
await Promise.resolve();
assert.equal(slots.retained(), 0);
assert.equal(slots.current(), null);
assert.throws(() => retireGeneratedTaskSlots(generated + generated), /shape-drift/);
"""
        with tempfile.TemporaryDirectory() as owned:
            root = Path(owned)
            (root / "async_waiters.mjs").write_bytes(
                (ROOT / "tools/typescript_guest/async_waiters.mjs").read_bytes()
            )
            (root / "test.mjs").write_text(source, encoding="utf-8")
            result = subprocess.run(
                [shutil.which("node"), str(root / "test.mjs")],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
