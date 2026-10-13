// The pinned generator keeps an idle sync-import waiter in its component state.
// Allocate that intrinsic Promise only while there is an actual import to await.
export function lazySyncImportWaiters(source) {
  const replacements = [
    ['  #syncImportWait = promiseWithResolvers();', '  #syncImportWait = null;'],
    ['    this.#syncImportWait = promiseWithResolvers();\n    existing.resolve();',
      '    this.#syncImportWait = null;\n    if (existing) existing.resolve();'],
    ['  async waitForSyncImportCallEnd() {\n    await this.#syncImportWait.promise;\n  }',
      '  async waitForSyncImportCallEnd() {\n' +
      '    if (!this.#callingAsyncImport) return;\n' +
      '    this.#syncImportWait ??= promiseWithResolvers();\n' +
      '    await this.#syncImportWait.promise;\n  }'],
  ];
  for (const [before, after] of replacements) {
    if (source.split(before).length !== 2) {
      throw new Error('selected-runtime-sync-import-waiter-shape-drift');
    }
    source = source.replace(before, after);
  }
  return source;
}

export function retireGeneratedTaskSlots(source) {
  const replacements = [
    ['  #nextTaskPromise = Promise.resolve(true);', '  #nextTaskPromise = null;'],
    ['      await this.#nextTaskPromise;',
      '      if (this.#nextTaskPromise !== null) await this.#nextTaskPromise;'],
    ['        this.#nextTaskPromise = next.promise;',
      '        this.#nextTaskPromise = next?.promise ?? null;'],
    ['        placeholder.completed = true;\n      }),',
      '        placeholder.completed = true;\n' +
      '        this.#nextTaskQueue = this.#nextTaskQueue.filter(entry => entry !== placeholder);\n' +
      '        if (this.#nextTaskPromise === placeholder.promise) this.#nextTaskPromise = null;\n' +
      '      }),'],
  ];
  for (const [before, after] of replacements) {
    if (source.split(before).length !== 2) {
      throw new Error('selected-runtime-task-slot-shape-drift');
    }
    source = source.replace(before, after);
  }
  return source;
}

export function applicationRealmImportPromises(source) {
  const anchor = 'const __lsfImports = contentGlobal.__lsfAsyncImportBridge;\n';
  if (source.split(anchor).length !== 2) {
    throw new Error('selected-runtime-import-promise-realm-shape-drift');
  }
  const helper = `
const __lsfApplicationPromise = contentGlobal.Promise;
const __lsfAsyncFunctionPrototype = Object.getPrototypeOf(async function () {});
function __lsfApplicationAsyncFunction(original) {
  const callable = {
    [original.name](...args) {
      return __lsfApplicationPromise.resolve(Reflect.apply(original, this, args));
    }
  }[original.name];
  Object.defineProperty(callable, 'length', {value: original.length});
  return callable;
}
function __lsfNormalizeAsyncMethods(target) {
  if (!target) return;
  for (const key of Reflect.ownKeys(target)) {
    const descriptor = Object.getOwnPropertyDescriptor(target, key);
    if (typeof descriptor.value === 'function' &&
        Object.getPrototypeOf(descriptor.value) === __lsfAsyncFunctionPrototype) {
      Object.defineProperty(target, key,
        {...descriptor, value: __lsfApplicationAsyncFunction(descriptor.value)});
    }
  }
}
function __lsfApplicationBuiltinModule(name, exports) {
  const normalized = {};
  for (const [key, original] of Object.entries(exports)) {
    let value = original;
    if (typeof original === 'function') {
      if (Object.getPrototypeOf(original) === __lsfAsyncFunctionPrototype) {
        value = __lsfApplicationAsyncFunction(original);
      } else {
        __lsfNormalizeAsyncMethods(original);
        __lsfNormalizeAsyncMethods(original.prototype);
      }
    }
    Object.defineProperty(normalized, key,
      {value, enumerable: true, configurable: true, writable: true});
  }
  defineBuiltinModule(name, normalized);
}
`;
  return source.replace(/^defineBuiltinModule\(/gm, '__lsfApplicationBuiltinModule(')
    .replace(anchor, anchor + helper);
}
