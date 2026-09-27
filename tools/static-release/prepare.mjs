import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {realpath} from 'node:fs/promises';
import {requireValue} from './model.mjs';
import {boundedJson, jsonBytes, privateDirectory, readBytes, sha256, writeJson} from './files.mjs';
import {native, run} from './process.mjs';
import {ASSEMBLY} from './evidence.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const record = (name, bytes) => ({name, digest: sha256(bytes), size: bytes.length});

export async function prepare({cli, python, buildOutput, inventory, repository, output}) {
  requireValue(/^https:\/\/[a-zA-Z0-9.-]+\/[a-zA-Z0-9._/-]+$/.test(repository)
    && repository.length <= 512 && !repository.split('/').some(part => part === '.' || part === '..'), 'source-repository-label-required');
  const startedAt = Math.floor(Date.now() / 1000);
  const directory = await privateDirectory(output, true);
  // Each observer verifies its own exact input identities before and after work.
  // Source/toolchain/build inputs in this inventory remain operator assertions.
  const input = JSON.parse((await readBytes(inventory, 65536)).toString('utf8'));
  requireValue(Array.isArray(input.observations) && input.observations.length <= 8, 'capture-observations-required');
  const materials = [];
  const retainedInputs = [];
  for (const [name, filename, maximum] of [
    ['package-assembler', cli, 256 * 1024 * 1024], ['node', process.execPath, 256 * 1024 * 1024],
    ['python', python, 256 * 1024 * 1024], ['reviewed-public-inventory', inventory, 65536],
  ]) {
    const actual = await realpath(filename), material = record(name, await readBytes(actual, maximum));
    materials.push(material); retainedInputs.push({actual, maximum, digest: material.digest});
  }
  const recipe = [];
  for (const name of ['tools/static_site.py', 'tools/static-release/prepare.mjs', 'tools/static-release/files.mjs',
    'tools/static-release/process.mjs', 'tools/static-release/evidence.mjs',
    'tools/static-release/model.mjs', 'tools/static-release/release.mjs']) {
    const actual = path.join(root, name), material = record(name, await readBytes(actual, 1024 * 1024));
    recipe.push(material); retainedInputs.push({actual, maximum: 1024 * 1024, digest: material.digest});
  }
  materials.push(record('build-recipe', jsonBytes(recipe)));
  const toolchain = jsonBytes({schemaVersion: 'latent.static.assembly-tools.v1', nodeVersion: process.version,
    materials: materials.filter(item => ['node', 'python', 'package-assembler'].includes(item.name))});
  materials.push(record('toolchain-config', toolchain));
  await writeJson(path.join(directory, 'recipe.json'), recipe);
  await writeJson(path.join(directory, 'toolchain.json'), JSON.parse(toolchain));
  const captured = JSON.parse((await run(python, [path.join(root, 'tools/static_site.py'), '--build-output', buildOutput,
    '--input', inventory, '--output', path.join(directory, 'inputs')], directory)).toString('utf8'));
  requireValue(captured.schemaVersion === 'latent.static-site.capture.v1' && captured.frameworkBuildExecuted === false,
    'supplied-static-capture-required');
  const source = captured.observations.find(item => item.kind === 'source');
  requireValue(source && captured.observations.filter(item => item.kind === 'source').length === 1, 'source-observation-required');
  // The capture adapter checked these supplied bytes against the reviewed input.
  materials.push({name: 'source-snapshot', digest: source.digest, size: source.size});
  materials.push(record('static-capture-observation', jsonBytes(captured)));
  const summary = await native(cli, ['package', 'build', '--source', path.join(directory, 'inputs/package-source.json'),
    '--input-root', path.join(directory, 'inputs'), '--sbom-inputs', path.join(directory, 'inputs/sbom-inputs.json'),
    '--output-dir', path.join(directory, 'package'), '--validate-web'], directory);
  requireValue(summary.kind === 'browser-assets' && summary.componentDigest === null
    && summary.sbomInventoryDigest && summary.webBuildOutputs, 'componentless-sbom-package-required');
  const outputs = summary.webBuildOutputs;
  for (const item of retainedInputs) requireValue(sha256(await readBytes(item.actual, item.maximum)) === item.digest,
    'assembly-tool-or-input-changed');
  const observation = {formatVersion: 1, buildType: ASSEMBLY,
    source: {repository, revision: source.digest.slice(7), snapshotDigest: source.digest,
      repositoryTrust: 'operator-asserted', capture: 'explicit-input-files'},
    outputsDigest: outputs.digest, outputsCount: outputs.count, outputsBytes: Number(outputs.bytes),
    materials: materials.sort((a, b) => a.name.localeCompare(b.name, 'en')),
    parameters: {assembler: 'lsf-web-package-assembly', recipeVersion: 1, inputMode: 'explicit-supplied-files'},
    startedAt, finishedAt: Math.floor(Date.now() / 1000), reproducibility: 'not-checked', hermetic: false,
    dependencyCompleteness: 'declared-inputs-incomplete'};
  requireValue(observation.finishedAt - startedAt <= 3600 && Number.isSafeInteger(observation.outputsBytes), 'assembly-observation-bound');
  const observationBytes = jsonBytes(observation);
  boundedJson(observationBytes, 32768);
  await writeJson(path.join(directory, 'observation.json'), observation);
  const receipt = {schemaVersion: 'latent.static.prepared.v1', packageDigest: summary.packageDigest,
    observationDigest: sha256(observationBytes), inputObservationTrust: 'operator-supplied', frameworkBuildExecuted: false,
    assemblyExecuted: true, reproducibility: 'not-checked', hermetic: false,
    dependencyCompleteness: 'declared-inputs-incomplete', sbomInventoryDigest: summary.sbomInventoryDigest};
  await writeJson(path.join(directory, 'PREPARE-COMPLETE.json'), receipt);
  return receipt;
}
