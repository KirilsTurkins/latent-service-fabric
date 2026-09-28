// A source-built CLI qualification must not claim released-binary authentication.
import {qualify} from '../static-release/qualification.mjs';
import {readdir} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
await qualify(process.argv[2], undefined, undefined, false);
const candidates = (await readdir(os.tmpdir())).filter(name => name.startsWith('lsf-frontend-'));
if (candidates.length !== 1) throw new Error('one-owned-harbor-input-workspace-required');
console.log(JSON.stringify({prepared: true, work: path.join(os.tmpdir(), candidates[0]), releasedBinary: false}));
