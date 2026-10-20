"""Normal captured Ky/Wretch callers; native execution is a separate gate."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil

from tools import typescript_dependency_authoring as authoring
from tools.application_dependencies import verify_inputs
from tools.npm_lock_authoring import create_lock
from tools.phase2_operator_process import require
from tools.qualify_typescript_fetch_runtime import project as fetch_project
from tools.rust_capsule_project import ROOT, digest, inventory, read_file, snapshot
from tools.typescript_application_dependencies import resolve
from tools.typescript_guest.runtime_profile import IMPORT_PROFILE

PACKAGES = {'ky': '2.2.0', 'wretch': '3.0.9'}
INTEGRITIES = {
    'ky': 'sha512-4+B63kyZt+Y8snQiUGydK1vgY9xYQJZEh9K/nIAIEts+gYJzy1EiAw3BbK8xpWRuWUpN70SNCMjqRGTm75xxIA==',
    'wretch': 'sha512-RXJQp5aOBfHQaDCLRyFXQooWDBOHrQxVgCH/6OFaFPBKjeUiXMQ3NV1b8qqI7CR+v4meVBWYs242P8n+rWRjzA==',
}
MAIN = b'''import type * as Contract from '../generated/interfaces/examples-typescript-fetch-api.js';
import {request, initialized} from './default-client.js';
if (!initialized) throw new Error('published-fetch-default-globals-unavailable');
let calls = 0;
function diagnostic(error: unknown): string {
  const kind = error instanceof TypeError ? 'TypeError' : error instanceof RangeError ? 'RangeError' :
    error instanceof ReferenceError ? 'ReferenceError' : error instanceof SyntaxError ? 'SyntaxError' :
    error instanceof Error ? 'Error' : 'other';
  const labels = new Map([
    ['lsf-fetch-buffered-v1:unsupported:streaming-body', 'streaming-body-unavailable'],
    ['body-already-used', 'body-already-used'],
    ['lsf-fetch-buffered-v1:unsupported:response-status-text', 'status-text-unavailable'],
  ]);
  const label = error instanceof Error ? labels.get(error.message) ?? 'unknown' : 'unknown';
  return `diagnostic:${kind}:${label}`;
}
export const api: typeof Contract = {
  async run(mode, url) {
    if (++calls !== 1) throw new Error('published-fetch-activation-state-reused');
    try {
      if (mode === 5) {
        const response = new Response('reader');
        const reader = response.body!.getReader();
        const first = await reader.read(), second = await reader.read();
        if (first.done || first.value.length !== 6 || !second.done || !response.bodyUsed)
          throw new Error('published-fetch-buffered-reader-probe');
        reader.releaseLock();
        return '1|buffered-reader-ready';
      }
      if (mode === 6) {
        const response = new Response('{"value":42}');
        if ((await response.json()).value !== 42 || !response.bodyUsed)
          throw new Error('published-fetch-buffered-json-probe');
        return '1|buffered-json-ready';
      }
      return `1|${await request(mode, url)}`;
    } catch (error) { return diagnostic(error); }
  },
};
'''
CLIENT = '''import ky, {HTTPError} from 'ky';
import wretch from 'wretch';
import {read} from '@PRIVATE@';
export const initialized = typeof fetch === 'function' && typeof Request === 'function' &&
  typeof Response === 'function' && typeof Headers === 'function' &&
  typeof ky === 'function' && typeof wretch === 'function';
export async function request(mode: number, url: string): Promise<string> {
  if (mode === 0) return `ky:${JSON.stringify(await ky.get(url).json())}`;
  if (mode === 1) return `wretch:${JSON.stringify(await wretch(url).get().json())}`;
  if (mode === 2) return `outside:${JSON.stringify(await read(url))}`;
  if (mode === 3) {
    try { await ky.get(url).json(); }
    catch (error) {
      if (error instanceof HTTPError && error.response.status === 404) return 'ky:error:404';
      if (error instanceof TypeError && error.message === 'lsf-fetch-buffered-v1:unsupported:response-status-text')
        return 'ky:unsupported:response-status-text';
      throw error;
    }
    throw new Error('published-fetch-ky-missing-http-error');
  }
  if (mode === 4) {
    try { await wretch(url).get().json(); }
    catch (error) {
      if (error instanceof wretch.WretchError && error.status === 404)
        return 'wretch:error:404';
      throw error;
    }
    throw new Error('published-fetch-wretch-missing-http-error');
  }
  throw new TypeError('published-fetch-mode');
}
'''
PRIVATE = b'''import wretch from 'wretch';
let calls = 0;
export async function read(url) {
  if (++calls !== 1) throw new Error('outside-fetch-state-reused');
  return await wretch(url).get().json();
}
'''


def project(directory: Path, private_name: str) -> Path:
    require(re.fullmatch(r'outside-fetch-[a-z0-9-]{1,32}', private_name) is not None,
            'published-fetch-private-identity')
    app = fetch_project(directory)
    (app/'src/main.ts').write_bytes(MAIN)
    (app/'src/default-client.ts').write_bytes(CLIENT.replace('@PRIVATE@', private_name).encode())
    lock = json.loads(read_file(app/'sdk-lock.json'))
    lock['template']['sourceDigest'] = digest(MAIN)
    (app/'sdk-lock.json').write_bytes((json.dumps(lock, indent=2)+'\n').encode())
    return app


def capture(app: Path, outside: Path, private_name: str, private_version: str) -> dict:
    require(re.fullmatch(r'outside-fetch-[a-z0-9-]{1,32}', private_name) is not None
            and re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', private_version) is not None,
            'published-fetch-private-identity')
    owner = app.parent.resolve(strict=True)
    require(outside.parent.resolve(strict=True) == owner and ROOT != owner
            and ROOT not in owner.parents and not outside.exists(), 'published-fetch-owned-outside-source')
    outside.mkdir(mode=0o700)
    declaration = {'name': private_name, 'version': private_version, 'type': 'module',
        'license': 'Apache-2.0', 'exports': {'types': './index.d.ts', 'import': './index.mjs'},
        'dependencies': {'wretch': PACKAGES['wretch']}}
    (outside/'package.json').write_bytes((json.dumps(declaration, indent=2)+'\n').encode())
    (outside/'index.mjs').write_bytes(PRIVATE)
    (outside/'index.d.ts').write_bytes(b'export function read(url: string): Promise<unknown>;\n')
    sdk = read_file(app/'sdk-lock.json')
    for name, version in PACKAGES.items():
        authoring.edit(app, 'add', identity=name, version=version)
    authoring.edit(app, 'add', identity=private_name, local=outside)
    node = Path(shutil.which('node') or 'missing-node')
    npm = node.parent/'node_modules/npm/bin/npm-cli.js' if os.name == 'nt' else Path(shutil.which('npm') or 'missing-npm').resolve()
    native = create_lock(app, node=node, npm=npm)
    lock = json.loads(read_file(app/'package-lock.json'))
    for name, version in PACKAGES.items():
        row = lock['packages']['node_modules/'+name]
        require(row['version'] == version and row['integrity'] == INTEGRITIES[name],
                'published-fetch-original-package-identity')
    candidate = app/'target/published-fetch-dependencies.candidate.json'
    candidate.parent.mkdir(exist_ok=True)
    resolve(app, candidate, node=node, npm=npm,
        selected={'runtimeProfile': IMPORT_PROFILE, 'conditions': ['browser']})
    authoring.review(app, candidate, digest(read_file(candidate)))
    accepted = verify_inputs(app, 'typescript')
    require(accepted is not None and accepted.lock['selection']['runtimeProfile'] == IMPORT_PROFILE
            and accepted.lock['selection']['conditions'] == ['browser'], 'published-fetch-reviewed-profile')
    # Resolve the exact created directory again before recursive removal.
    require(not outside.is_symlink() and outside.resolve(strict=True).parent == owner,
            'published-fetch-source-removal-scope')
    shutil.rmtree(outside)
    require(verify_inputs(app, 'typescript').lock == accepted.lock
            and read_file(app/'sdk-lock.json') == sdk, 'published-fetch-offline-or-sdk-changed')
    return {'source': digest(inventory(snapshot(app))), 'nativeLock': native,
        'acceptedLock': digest(read_file(app/'latent.dependencies.lock.json')),
        'packages': {name: {'version': version, 'integrity': INTEGRITIES[name]}
                     for name, version in PACKAGES.items()},
        'privateConsumer': {'identity': private_name, 'version': private_version,
            'module': digest(PRIVATE), 'outsideOriginalRemoved': True},
        'defaultGlobals': True, 'applicationFetchInjection': False,
        'compilerExecuted': False, 'signedProviderExecution': 'pending'}
