import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import {createRequire} from 'node:module';
import {test} from 'node:test';
import loader from '../plugins/code-word-wrap-loader.cjs';
import plugin from '../plugins/code-word-wrap.mjs';

const require = createRequire(import.meta.url);
const hookPath = path.join(path.dirname(require.resolve('@docusaurus/theme-common')), 'hooks/useCodeWordWrap.js');
const upstream = fs.readFileSync(hookPath, 'utf8');

function hook(source, enabled = false) {
  const effects = [], states = [], listeners = new Map();
  const ref = {current: null};
  const context = {
    useState(initial) {
      const index = states.length;
      states.push(index === 0 ? enabled : initial);
      return [states[index], value => {states[index] = typeof value === 'function' ? value(states[index]) : value;}];
    },
    useCallback: callback => callback,
    useEffect: callback => effects.push(callback),
    useRef: () => ref,
    useMutationObserver() {},
    window: {
      addEventListener: (name, callback) => listeners.set(name, callback),
      removeEventListener: name => listeners.delete(name),
    },
  };
  // Execute the installed hook itself with observable lifecycle ports. React
  // clears ref.current before its passive effects' cleanup on navigation.
  const code = source.replace(/^import .*;\r?\n/gm, '').replace('export function useCodeWordWrap', 'function useCodeWordWrap');
  const value = vm.runInNewContext(`${code}\nuseCodeWordWrap();`, context);
  return {value, ref, states, listeners, effects};
}

function block() {
  const code = {style: {}, hasAttribute: () => Object.keys(code.style).length > 0,
    removeAttribute: () => {code.style = {};}};
  return {scrollWidth: 200, clientWidth: 200, closest: () => null,
    querySelector: () => code, code};
}

test('the installed code hook tolerates late callbacks after ref detachment and retains cleanup', () => {
  const original = hook(upstream);
  original.ref.current = block();
  const originalCleanup = original.effects.map(effect => effect()).filter(value => typeof value === 'function');
  original.ref.current = null;
  assert.throws(() => original.listeners.get('resize')(), /scrollWidth/);
  originalCleanup.forEach(cleanup => cleanup());

  const fixed = hook(loader.call({}, upstream));
  fixed.ref.current = block();
  const cleanup = fixed.effects.map(effect => effect()).filter(value => typeof value === 'function');
  fixed.ref.current = null;
  assert.doesNotThrow(() => fixed.listeners.get('resize')());
  assert.doesNotThrow(() => fixed.value.toggle());
  assert.equal(fixed.states[0], false);
  cleanup.forEach(value => value());
  assert.equal(fixed.listeners.size, 0);
});

test('mounted code retains overflow detection, wrapping and explicit unwrap behavior', () => {
  const fixed = hook(loader.call({}, upstream));
  fixed.ref.current = block();
  fixed.effects.forEach(effect => effect());
  assert.equal(fixed.states[1], false);
  fixed.ref.current.scrollWidth = 400;
  fixed.listeners.get('resize')();
  assert.equal(fixed.states[1], true);
  fixed.value.toggle();
  assert.equal(fixed.ref.current.code.style.whiteSpace, 'pre-wrap');
  assert.equal(fixed.ref.current.code.style.overflowWrap, 'anywhere');
  assert.equal(fixed.states[0], true);
  fixed.ref.current.scrollWidth = 200;
  fixed.listeners.get('resize')();
  assert.equal(fixed.states[1], true);
  const enabled = hook(loader.call({}, upstream), true);
  enabled.ref.current = fixed.ref.current;
  enabled.value.toggle();
  assert.equal(Object.keys(enabled.ref.current.code.style).length, 0);
  assert.equal(enabled.states[0], false);
});

test('the lifecycle patch is confined to the exact pinned upstream hook and rejects drift', () => {
  const rule = plugin().configureWebpack().module.rules[0];
  assert.deepEqual(rule.include, [hookPath]);
  assert.equal(rule.enforce, 'pre');
  assert.throws(() => loader.call({}, `${upstream}\n// changed input`), /changed Docusaurus hook/);
});
