"""Generated waiters preserve real import suspension without idle pending work."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class TypeScriptAsyncWaiterTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "requires Node")
    def test_idle_state_actual_shared_wait_and_successive_imports(self):
        source = r"""
import assert from 'node:assert/strict';
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
}; ComponentAsyncState`;
const State = eval(lazySyncImportWaiters(generated));
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
}; Slots`;
const Slots = eval(retireGeneratedTaskSlots(generated));
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
