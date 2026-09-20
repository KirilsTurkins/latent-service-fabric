import {parseArgs} from 'node:util';
import {readSource, repositoryRoot, requireValue} from '../lib/repository.mjs';
import {createSnapshot} from '../lib/versions/snapshot.mjs';
import {storeSnapshot} from '../lib/versions/storage.mjs';
const keys = ['version', 'runtimeVersion', 'runtimeSource', 'documentationSource', 'exampleSource', 'profile'];
const {values} = parseArgs({options: Object.fromEntries(keys.map(key => [key, {type: 'string'}])), allowPositionals: false});
requireValue(keys.every(key => typeof values[key] === 'string'), 'Supply every documented snapshot identity explicitly');
const policy = JSON.parse(readSource(repositoryRoot, 'website/content/assets.json').toString());
const snapshot = createSnapshot(repositoryRoot, values, policy);
const identity = storeSnapshot(repositoryRoot, snapshot);
console.log(JSON.stringify({version: snapshot.manifest.version, snapshotIdentity: identity, documents: snapshot.documents.length,
  examples: snapshot.bundle.examples.length, runtimeSource: snapshot.manifest.runtimeSource, documentationSource: snapshot.manifest.documentationSource}));
