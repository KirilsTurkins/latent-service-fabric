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
