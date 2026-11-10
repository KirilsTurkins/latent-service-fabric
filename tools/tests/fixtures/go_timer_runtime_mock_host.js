const fs = require('node:fs');
const { WASI } = require('node:wasi');

function assert(ok, message) {
  if (!ok) throw new Error(message);
}

class Probe {
  constructor(path, iteratorFault) {
    this.clock = 1000000000n;
    this.nextOwner = 1n;
    this.nextSubtask = 1;
    this.context = 0;
    this.timers = new Map();
    this.owners = new Map();
    this.pending = new Map();
    this.records = [];
    this.observations = [];
    this.denyNextStart = false;
    this.denyNextStop = false;
    this.iteratorFault = iteratorFault;
    this.iteratorParked = new Set();
    this.iteratorSnapshots = new Map();
    this.denyIteratorPark = false;
    this.denyIteratorWake = false;
    const wasi = new WASI({ version: 'preview1', args: [], env: {}, preopens: {}, returnOnExit: true });
    const tokenResult = (ptr, id) => {
      const view = this.view();
      view.setUint32(ptr, 0, true);
      view.setBigUint64(ptr + 8, 1n, true);
      view.setBigUint64(ptr + 16, id, true);
    };
    const unitResult = ptr => this.view().setUint8(ptr, 0);
    const activation = {
      register: (kind, hasParent, generation, parent, ptr) => {
        const id = this.nextOwner++;
        tokenResult(ptr, id);
        this.owners.set(String(id), kind);
        this.records.push(['register', kind, String(id), hasParent, String(parent)]);
      },
      settle: (generation, id, ptr) => {
        assert(this.owners.delete(String(id)), 'settling missing mock owner ' + id);
        this.iteratorParked.delete(String(id));
        unitResult(ptr); this.records.push(['settle', String(id)]);
      },
      park: (generation, id, ptr) => {
        if (this.iteratorFault === undefined) { unitResult(ptr); return; }
        const key = String(id);
        assert(this.owners.get(key) === 0 && !this.iteratorParked.has(key), 'invalid iterator park');
        if (this.denyIteratorPark) {
          this.denyIteratorPark = false; this.records.push(['deny-iterator-park', key]);
          this.view().setUint8(ptr, 1); return;
        }
        this.iteratorParked.add(key); this.records.push(['iterator-park', key]); unitResult(ptr);
      },
      wake: (generation, id, ptr) => {
        if (this.iteratorFault === undefined) { unitResult(ptr); return; }
        const key = String(id);
        assert(this.owners.get(key) === 0 && this.iteratorParked.has(key), 'invalid iterator wake');
        if (this.denyIteratorWake) {
          this.denyIteratorWake = false; this.records.push(['deny-iterator-wake', key]);
          this.view().setUint8(ptr, 1); return;
        }
        this.iteratorParked.delete(key); this.records.push(['iterator-wake', key]); unitResult(ptr);
      },
      close: ptr => { unitResult(ptr); this.records.push(['close']); },
      'timer-start': (delay, periodic, period, hasParent, generation, parent, ptr) => {
        if (this.denyNextStart) {
          this.denyNextStart = false;
          this.view().setUint32(ptr, 1, true);
          this.records.push(['deny-start']);
          return;
        }
        const id = this.nextOwner++;
        tokenResult(ptr, id);
        this.timers.set(String(id), { delay, periodic, period });
        this.records.push(['start', String(id), String(delay)]);
      },
      'timer-stop': (generation, id, ptr) => {
        const key = String(id);
        if (this.denyNextStop) {
          this.denyNextStop = false;
          this.view().setUint8(ptr, 1);
          this.records.push(['deny-stop', key]);
          return;
        }
        assert(this.timers.delete(key), 'stopping missing mock timer ' + key);
        unitResult(ptr);
        this.records.push(['stop', key]);
      },
      '[async-lower]timer-next': (generation, id, ptr) => {
        const sid = this.nextSubtask++;
        assert(this.timers.has(String(id)), 'next on missing mock timer ' + id);
        this.pending.set(sid, { kind: 'timer', id: String(id), ptr });
        this.records.push(['next', String(id), sid]);
        return (sid << 4) | 1;
      },
    };
    const imports = {
      wasi_snapshot_preview1: wasi.wasiImport,
      'latent:clock/monotonic@0.1.0': { 'now-nanos': () => this.clock },
      'latent:clock/wall@0.1.0': { 'now-unix-millis': () => 1700000000000n },
      'latent:random/random@0.1.0': { 'u64-value': ptr => {
        const view = this.view();
        view.setUint32(ptr, 0, true);
        view.setBigUint64(ptr + 8, 0x1234567812345678n, true);
      } },
      'latent:runtime/activation@0.1.0': activation,
      '$root': {
        '[waitable-set-new]': () => 1,
        '[waitable-set-poll]': () => 0,
        '[waitable-set-drop]': () => {},
        '[waitable-join]': () => {},
        '[context-get-0]': () => this.context,
        '[context-set-0]': ptr => { this.context = ptr; },
        '[subtask-drop]': sid => { this.pending.delete(sid); },
      },
      fixture: {
        '[async-lower]wait': () => {
          const sid = this.nextSubtask++;
          this.pending.set(sid, { kind: 'fixture' });
          return (sid << 4) | 1;
        },
        observe: (kind, value) => {
          this.observations.push([kind, value]);
          this.records.push(['observe', kind, value]);
          if (this.iteratorFault !== undefined && kind >= 50 && kind <= 55) {
            const tasks = [...this.owners].filter(([, ownerKind]) => ownerKind === 0).map(([id]) => id);
            this.iteratorSnapshots.set(kind, {tasks, parked: tasks.filter(id => this.iteratorParked.has(id))});
            if (kind === 50 && this.iteratorFault === 'initial-park') this.denyIteratorPark = true;
            if (kind === 51 && this.iteratorFault === 'switch-park') this.denyIteratorPark = true;
            if (kind === 51 && this.iteratorFault === 'switch-wake') this.denyIteratorWake = true;
            if (kind === 55 && this.iteratorFault === 'exit-wake') this.denyIteratorWake = true;
          }
        },
      },
    };
    const mod = new WebAssembly.Module(fs.readFileSync(path));
    this.instance = new WebAssembly.Instance(mod, imports);
    wasi.initialize(this.instance);
  }

  view() { return new DataView(this.instance.exports.memory.buffer); }
  begin(mode) { return this.instance.exports.begin(mode); }
  find(kind) {
    const entries = [...this.pending.entries()].filter(([, entry]) => entry.kind === kind);
    assert(entries.length === 1, 'expected one pending ' + kind + ': ' + JSON.stringify(entries));
    return entries[0];
  }
  deliver(sid, cancelled = false) {
    const event = this.pending.get(sid);
    assert(event, 'unknown pending subtask ' + sid);
    if (event.kind === 'timer') {
      this.view().setUint8(event.ptr, cancelled ? 1 : 0);
      this.view().setUint8(event.ptr + 8, cancelled ? 3 : 0);
    }
    return this.instance.exports.resume(1, sid, 2);
  }
}

function resetPair(path, mode) {
  const p = new Probe(path);
  const first = p.begin(mode);
  const [fixtureId] = p.find('fixture');
  const [timerId, original] = p.find('timer');
  assert((first & 15) === 2, 'initial activation did not wait');
  const mid = p.deliver(fixtureId);
  const oldStopped = p.records.some(x => x[0] === 'stop' && x[1] === original.id);
  assert(oldStopped, 'first Reset did not stop the original timer');
  assert(!p.observations.some(x => x[0] === 1 || x[0] === 2), 'gate failed to hold public operations');
  p.clock += 20000000n;
  assert(!p.observations.some(x => x[0] === 6 || x[0] === 30), 'old callback fired after stop');
  const end = p.deliver(timerId, true);
  const values = Object.fromEntries(p.observations.map(([k, v]) => [k, v]));
  assert(values[1] === 1, 'first Reset did not report active');
  assert(values[2] === 1, 'second public operation did not observe the replacement');
  if (mode === 1) assert(values[3] === 1, 'final Stop did not observe the replacement');
  assert(p.timers.size === 0, 'timer operation left an original timer owner');
  assert((end & 15) === 0, 'timer activation did not complete');
  assert(!p.observations.some(x => x[0] === 6 || x[0] === 30), 'stopped callback was observed');
  console.log(JSON.stringify({case: 'pair-' + mode, first, mid, end,
    observations: p.observations, liveTimers: [...p.timers.keys()], records: p.records}));
}

function firing(path, mode) {
  const p = new Probe(path);
  const first = p.begin(mode);
  const [sid, original] = p.find('timer');
  assert((first & 15) === 2, 'firing activation did not wait');
  p.clock += 20000000n;
  const end = p.deliver(sid, false);
  const values = Object.fromEntries(p.observations.map(([k, v]) => [k, v]));
  const expected = mode === 2 ? [[10, 1], [11, 0], [12, 1]] : [[20, 1], [21, 0], [22, 1]];
  for (const [kind, value] of expected) assert(values[kind] === value, 'wrong callback result ' + kind);
  assert(p.timers.size === 0, 'firing scenario retained timer owners');
  assert((end & 15) === 0, 'firing activation did not finish');
  const retired = p.records.findIndex(x => x[0] === 'stop' && x[1] === original.id);
  const invoked = p.records.findIndex(x => x[0] === 'observe' && x[1] === expected[0][0]);
  assert(retired >= 0 && retired < invoked, 'original callback owner not retired before app continuation');
  console.log(JSON.stringify({case: 'fire-' + mode, first, end,
    observations: p.observations, records: p.records}));
}

function idleDrain(path) {
  const p = new Probe(path);
  const first = p.begin(5);
  const [fixtureId] = p.find('fixture');
  const [timerId, original] = p.find('timer');
  assert((first & 15) === 2, 'idle-drain activation did not initially wait');
  const mid = p.deliver(fixtureId);
  assert(p.records.some(x => x[0] === 'close'), 'activation close was not called');
  assert(p.records.some(x => x[0] === 'stop' && x[1] === original.id), 'idle drain did not stop original timer');
  assert(p.observations.some(x => x[0] === 40), 'idle-drain setup did not finish');
  assert(!p.observations.some(x => x[0] === 41), 'idle drain bypassed pending physical fence');
  const end = p.deliver(timerId, true);
  assert(p.observations.some(x => x[0] === 41), 'idle drain did not return after fence completion');
  assert(!p.observations.some(x => x[0] === 46), 'stopped channel timer delivered a value');
  assert(p.timers.size === 0 && (end & 15) === 0, 'idle drain did not complete cleanly');
  console.log(JSON.stringify({case: 'idle-drain', first, mid, end,
    observations: p.observations, records: p.records}));
}

function trappedGateHolder(path) {
  const p = new Probe(path);
  p.begin(6);
  const [fixtureId] = p.find('fixture');
  const [timerId] = p.find('timer');
  p.deliver(fixtureId);
  assert(!p.observations.some(x => x[0] === 1 || x[0] === 2), 'gate holder or waiter escaped before denial');
  p.denyNextStart = true;
  let trapped = false;
  try { p.deliver(timerId, true); }
  catch (error) { if (!(error instanceof WebAssembly.RuntimeError)) throw error; trapped = true; }
  assert(trapped, 'timer admission denial did not trap');
  assert(p.records.some(x => x[0] === 'deny-start'), 'timer admission denial was not reached');
  assert(!p.observations.some(x => x[0] === 1 || x[0] === 2), 'trapped gate operation returned to application');
  assert([...p.owners.values()].filter(kind => kind === 0).length >= 2, 'expected trapped task owners were lost');
  console.log(JSON.stringify({case: 'trap-gate-holder', liveTaskOwners: [...p.owners.entries()].filter(x => x[1] === 0),
    liveTimers: [...p.timers.keys()], records: p.records}));
}

function trappedCallback(path) {
  const p = new Probe(path);
  p.begin(2);
  const [sid, original] = p.find('timer');
  p.clock += 20000000n;
  p.denyNextStop = true;
  let trapped = false;
  try { p.deliver(sid, false); }
  catch (error) { if (!(error instanceof WebAssembly.RuntimeError)) throw error; trapped = true; }
  assert(trapped, 'callback timer-stop refusal did not trap');
  assert(p.timers.has(original.id), 'unconfirmed callback owner was lost');
  assert(p.records.some(x => x[0] === 'register' && x[1] === 0 && x[4] === original.id),
    'callback continuation did not retain original parent');
  assert(!p.observations.some(x => x[0] === 10), 'callback application continuation ran after trap');
  console.log(JSON.stringify({case: 'trap-callback-retirement', liveTimers: [...p.timers.keys()], records: p.records}));
}

function iterator(path, fault) {
  const p = new Probe(path, fault);
  let result, trapped = false;
  try { result = p.begin(7); }
  catch (error) { if (!(error instanceof WebAssembly.RuntimeError)) throw error; trapped = true; }
  if (fault === 'none') {
    assert(!trapped && (result & 15) === 0, 'iterator activation did not finish');
    for (const stage of [50, 51, 52, 53, 54]) assert(p.iteratorSnapshots.has(stage), 'missing iterator stage ' + stage);
    const root = p.iteratorSnapshots.get(50).tasks;
    const child = p.iteratorSnapshots.get(51).tasks.filter(id => !root.includes(id));
    assert(root.length === 1 && child.length === 1, 'unexpected iterator task owners');
    assert(p.iteratorSnapshots.get(51).parked.includes(child[0]), 'new iterator child is not parked');
    assert(p.iteratorSnapshots.get(52).parked.includes(root[0]), 'iterator caller is not parked');
    assert(p.iteratorSnapshots.get(53).parked.includes(child[0]), 'yielded iterator is not parked');
    assert(p.observations.some(([kind, value]) => kind === 53 && value === 42), 'wrong iterator value');
    assert(!p.iteratorSnapshots.get(54).tasks.includes(child[0]), 'stopped iterator task survived');
    assert(p.owners.size === 0, 'iterator activation retained mock owners');
  } else {
    assert(trapped, 'iterator accounting refusal did not trap');
    const denied = fault.endsWith('wake') ? 'deny-iterator-wake' : 'deny-iterator-park';
    assert(p.records.some(x => x[0] === denied), 'iterator refusal was not reached');
    if (fault === 'exit-wake') {
      const root = p.iteratorSnapshots.get(50).tasks[0];
      const child = p.iteratorSnapshots.get(51).tasks.find(id => id !== root);
      const childQueue = p.records.find(x => x[0] === 'register' && x[1] === 3 && x[4] === child)[2];
      const taskDrop = p.records.findIndex(x => x[0] === 'settle' && x[1] === child);
      const queueDrop = p.records.findIndex(x => x[0] === 'settle' && x[1] === childQueue);
      const refusal = p.records.findIndex(x => x[0] === denied && x[1] === root);
      assert(queueDrop >= 0 && queueDrop < taskDrop && taskDrop < refusal, 'exited child was not settled before the refused wake');
      assert(p.owners.get(root) === 0 && !p.iteratorSnapshots.has(54), 'refused caller resumed or lost its owner');
      assert([...p.owners.values()].filter(kind => kind === 3).length >= 1, 'original caller queue owner was lost');
    } else {
      assert(!p.iteratorSnapshots.has(52), 'iterator continued after accounting refusal');
      assert([...p.owners.values()].filter(kind => kind === 0).length >= 2, 'original task owners were lost');
      assert([...p.owners.values()].filter(kind => kind === 3).length >= 2, 'original queue owners were lost');
    }
    const before = JSON.stringify([...p.owners]);
    let retrapped = false;
    try { p.begin(7); } catch (error) { if (!(error instanceof WebAssembly.RuntimeError)) throw error; retrapped = true; }
    assert(retrapped && JSON.stringify([...p.owners]) === before, 'trapped core instance reused its owners');
  }
  console.log(JSON.stringify({case: 'iterator-' + fault, trapped, result,
    snapshots: [...p.iteratorSnapshots], owners: [...p.owners], records: p.records}));
}

const wasm = process.argv[2];
assert(wasm, 'expected the current runtime control Wasm path');
resetPair(wasm, 1);
resetPair(wasm, 4);
firing(wasm, 2);
firing(wasm, 3);
idleDrain(wasm);
trappedGateHolder(wasm);
trappedCallback(wasm);
for (const fault of ['none', 'initial-park', 'switch-park', 'switch-wake', 'exit-wake']) iterator(wasm, fault);
console.log('REAL_RUNTIME_WITH_MOCK_HOST=PASS');
