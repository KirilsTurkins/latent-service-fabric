import assert from 'node:assert/strict';
import { test } from 'node:test';
import { pathToFileURL } from 'node:url';
import { resolve } from 'node:path';
import { runInNewContext } from 'node:vm';
const base = process.env.LSF_TYPESCRIPT_OWNERS;
assert.ok(base, 'compile the exact capability owner and result modules');
const { Owner, Scope, drop } = await import(pathToFileURL(resolve(base, 'owner.js')));
const { call, unwrap } = await import(pathToFileURL(resolve(base, 'result.js')));

test('consumption is final on success, typed failure, and ordinary exceptions', () => {
  for (const failure of [undefined, { tag: 'uncertain' }, new Error('failure')]) {
    let operations = 0;
    const owner = new Owner(7n, () => { operations += 100; });
    try { owner.consume(value => { assert.equal(value, 7n); operations++; if (failure) throw failure; }); }
    catch (error) { assert.equal(error, failure); }
    owner.close();
    assert.throws(() => owner.consume(() => { operations++; }));
    assert.throws(() => owner.borrow(() => {}));
    assert.equal(operations, 1);
  }
});

test('borrows exclude reentry, consume and close, then unlock even after failure', () => {
  let dropped = 0;
  const owner = new Owner({}, () => dropped++);
  assert.throws(() => owner.borrow(() => {
    assert.throws(() => owner.close());
    assert.throws(() => owner.consume(() => {}));
    assert.throws(() => owner.borrow(() => {}));
    throw new Error('body');
  }));
  owner.close(); owner.close();
  assert.equal(dropped, 1);
});

test('scope closes all owners once in reverse order despite a destructor failure', () => {
  const order = [], scope = new Scope();
  for (let i = 0; i < 3; i++) scope.own(new Owner(i, value => {
    order.push(value); if (value === 1) throw new Error('drop');
  }));
  assert.throws(() => scope.close());
  scope.close();
  assert.deepEqual(order, [2, 1, 0]);
  assert.throws(() => scope.own(new Owner(3, value => order.push(value))));
  assert.deepEqual(order, [2, 1, 0, 3]);
});

test('scope refuses and closes owner 257 at its explicit bound', () => {
  const scope = new Scope(); let closed = 0;
  for (let i = 0; i < 256; i++) scope.own(new Owner(i, () => closed++));
  assert.throws(() => scope.own(new Owner(256, () => closed++)));
  scope.close();
  assert.equal(closed, 257);
});

test('resource destruction uses the pinned canonical symbol, not finalization', () => {
  let count = 0;
  const value = { [Symbol.dispose || Symbol.for('dispose')]() { assert.equal(this, value); count++; } };
  drop(value);
  assert.equal(count, 1);
  assert.throws(() => drop({}));
});

test('only closed declared error payloads become typed errors; traps remain traps', () => {
  const declared = Object.assign(new Error('component'), { payload: { tag: 'uncertain' } });
  const result = call(() => { throw declared; }, ['uncertain']);
  assert.deepEqual(result, { tag: 'err', val: { tag: 'uncertain' } });
  const foreign = runInNewContext("Object.assign(new Error('component'), { payload: { tag: 'uncertain' } })");
  assert.equal(foreign instanceof Error, false);
  assert.equal(call(() => { throw foreign; }, ['uncertain']).val.tag, 'uncertain');
  assert.throws(() => unwrap(result), value => value.tag === 'uncertain');
  for (const value of [new Error('trap'), { tag: 'uncertain' },
    Object.assign(new Error(), { payload: { tag: 'unreviewed' } }),
    Object.assign(new Error(), { payload: { tag: 'uncertain', extra: 1 } })]) {
    assert.throws(() => call(() => { throw value; }, ['uncertain']), error => error === value);
  }
  assert.equal(unwrap(call(() => (1n << 64n) - 1n, [])), (1n << 64n) - 1n);
});
