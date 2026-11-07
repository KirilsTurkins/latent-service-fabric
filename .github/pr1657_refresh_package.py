from pathlib import Path
import json
root = Path.cwd()
p = root / 'tools/rust_thread_http_combined_package.py'
s = p.read_text()
start = s.index('"""'); end = s.index('"""', start + 3) + 3
s = s[:start] + '''"""Package one source-captured corrected combined compiler observation.

The successful compiler job is distinct from its failed ancillary source-check
job and from the historical failed compiler event. Assembly does not recompile
an application, open the normal builder, or substitute unreviewed graph bytes.
"""''' + s[end:]
a = s.index('SOURCE = '); b = s.index('IMPORTS =', a)
s = s[:a] + '''CATALOGUE = ROOT / 'crates/latent-component-threading/src/rust_catalogue/combined-corrected-v1'
ORIGIN = read_json(CATALOGUE / 'origin.json', 64 * 1024)
SOURCE = ORIGIN['sourceCommit']
RUN, JOB, ARTIFACT = (ORIGIN[key] for key in ('run', 'job', 'artifact'))
PROFILE = 'rust-context40-combined-http-diagnostic-v1'
# Fixed host-owned selection, not filenames or hashes supplied by a caller.
MEMBERS = ('application-source-and-capture.tar.gz', 'source-inputs.json', 'raw-core.wasm',
           'combined-component.wasm', 'observation.json', 'rust-http-composition.json',
           'recipe-origin.json', 'recipe-inputs.json', 'rust-http-runtime.json')
require(set(ORIGIN['compilerMembers']) == set(MEMBERS), 'rust-combined-fixed-compiler-members')
PINS = {name: (ORIGIN['compilerMembers'][name]['bytes'],
               ORIGIN['compilerMembers'][name]['sha256'].removeprefix('sha256:')) for name in MEMBERS}
WRAPPED = ORIGIN['wrapped']
''' + s[b:]
a = s.index('def original_files('); b = s.index('\ndef projected_source(', a)
s = s[:a] + '''def original_files(artifact: Path) -> tuple[dict[str, bytes], dict]:
    identities = {}
    for name, (size, sha) in PINS.items():
        actual = file_identity(artifact / name, 32 * 1024 * 1024)
        require(actual == {'bytes': size, 'sha256': 'sha256:' + sha}, 'rust-http-thread-retained-member')
        identities[name] = actual
    expected = read_json(artifact / 'source-inputs.json', 64 * 1024)
    require(type(expected) is dict and 0 < len(expected) <= 256,
            'rust-http-thread-retained-snapshot-shape')
    files, seen, total = {}, set(), 0
    with tarfile.open(artifact / 'application-source-and-capture.tar.gz', 'r:gz') as archive:
        for ordinal, member in enumerate(archive):
            name, path = member.name, PurePosixPath(member.name)
            require(ordinal < 16_384 and member.isfile() and 0 <= member.size <= 4 * 1024 * 1024
                    and name and not path.is_absolute() and path.as_posix() == name
                    and all(part not in ('', '.', '..') for part in path.parts)
                    and name.casefold() not in seen, 'rust-http-thread-retained-archive-shape')
            seen.add(name.casefold())
            total += member.size
            require(total <= 128 * 1024 * 1024, 'rust-http-thread-retained-archive-bound')
            if name in expected:
                payload = archive.extractfile(member).read(member.size + 1)
                require({'size': len(payload), 'digest': digest(payload)} == expected[name],
                        'rust-http-thread-retained-source-identity')
                files[name] = payload
    require(set(files) == set(expected)
            and inventory(files) == read_file(artifact / 'source-inputs.json', 64 * 1024),
            'rust-http-thread-complete-retained-source')
    return files, identities


def validate_producer(observation: dict, composition: dict, recipe: dict,
                      recipe_inputs: dict, source_inventory: bytes, runtime: bytes) -> None:
    commands = observation['commands']
    require(observation['schemaVersion'] == 'latent.rust.http-thread-core-observation.v1'
            and observation['status'] == ORIGIN['compilerObservationStatus']
            and observation['stage'] == 'complete'
            and observation['actualApplicationCoreCompiled'] is True
            and observation['normalBuildComplete'] is False
            and observation['normalComponentGateRefused'] is True
            and observation['actualGuestExecuted'] is False
            and observation['httpCompositionIncluded'] is True
            and observation['capture']['sourceDigest'] == digest(source_inventory)
            and observation['originalCore']['digest'] == 'sha256:' + PINS['raw-core.wasm'][1]
            and observation['combinedComponent']['digest'] == 'sha256:' + PINS['combined-component.wasm'][1]
            and observation['retainedOriginalSource']['digest'] == 'sha256:' + PINS['application-source-and-capture.tar.gz'][1]
            and observation['httpPreparedReceiptDigest'] == digest(runtime)
            and type(commands) is list and 0 < len(commands) <= 128
            and all(row['exitCode'] == 0 for row in commands)
            and sum(row['stage'] == 'compile' for row in commands) == 1
            and [(row['stage'], row['exitCode']) for row in commands[-4:]] == [
                ('rust-http-exact-composition', 0), ('rust-http-final-validation', 0),
                ('rust-http-final-graph', 0), ('combined-component-graph', 0)],
            'rust-http-thread-completed-compiler-observation')
    rows = recipe['files']
    require(recipe['head'] == SOURCE and recipe['tree'] == ORIGIN['sourceTree']
            and type(rows) is list and 0 < len(rows) <= 256
            and len({row['path'] for row in rows}) == len(rows)
            and {row['path']: {'size': row['size'], 'digest': row['digest']} for row in rows} == recipe_inputs,
            'rust-http-thread-compiler-source-lineage')
    require(composition['selectedComponentDigest'] == 'sha256:' + PINS['combined-component.wasm'][1]
            and observation['httpComposition'] == {**composition,
                'diagnosticComposer': observation['diagnosticComposer'], 'diagnosticOnly': True,
                'diagnosticValidationFeatures': 'cm-threading,cm-async,cm-async-stackful,cm-more-async-builtins'}
            and composition['publicGraphUnchanged'] is True
            and composition['librarySourceRewritten'] is False
            and composition['signedExecutionQualification'] is False
            and composition['runtimeReceipt'] == digest(runtime)
            and set(composition['imports']) == set(IMPORTS)
            and composition['exports'] == ['examples:greeting/api@1.0.0'],
            'rust-http-thread-exact-composed-surface')


def producer(artifact: Path, files: dict[str, bytes]) -> tuple[dict, dict]:
    observation = read_json(artifact / 'observation.json', 512 * 1024)
    composition = read_json(artifact / 'rust-http-composition.json', 16 * 1024)
    validate_producer(observation, composition, read_json(artifact / 'recipe-origin.json', 128 * 1024),
                     read_json(artifact / 'recipe-inputs.json', 64 * 1024), inventory(files),
                     read_file(artifact / 'rust-http-runtime.json', 64 * 1024))
    return observation, composition

''' + s[b:]
s = s.replace('failure, composition = producer(artifact, files)', 'observed, composition = producer(artifact, files)')
s = s.replace("read_file(artifact / 'source-inputs.json', 16 * 1024)", "read_file(artifact / 'source-inputs.json', 64 * 1024)")
s = s.replace('retained-compiler-failure', 'retained-compiler-observation')
s = s.replace("read_file(artifact / 'FAILED.json', 512 * 1024)", "read_file(artifact / 'observation.json', 512 * 1024)")
s = s.replace("    catalogue = ROOT / 'crates/latent-component-threading/src/rust_catalogue'\n    component = framed(artifact, catalogue)", "    component = framed(artifact, CATALOGUE)")
s = s.replace("'compilerRunConclusion': 'failure', 'compilerFailureStage': failure['stage'],\n        'compilerFailureReason': failure['reason'], 'compositionAndValidationCommandsSucceeded': True,", """'compilerRunConclusion': ORIGIN['workflowConclusion'],
        'compilerJobConclusion': ORIGIN['producerJobConclusion'],
        'compilerWorkflowSource': ORIGIN['workflowSource'],
        'compilerObservationStatus': observed['status'],
        'workflowFailureOutsideCompilerJob': ORIGIN['workflowFailureOutsideCompilerJob'],
        'compositionAndValidationCommandsSucceeded': True,""")
s = s.replace("'applicationRecompiled': False", "'applicationRecompiled': True, 'applicationRecompiledDuringAssembly': False")
s = s.replace("for row in failure['tools']", "for row in observed['tools']")
s = s.replace("'originalCompilerRunConclusion': 'failure'", "'compilerRunConclusion': ORIGIN['workflowConclusion'],\n        'compilerJobConclusion': ORIGIN['producerJobConclusion']")
s = s.replace("'tools/rust_combined_http_materials.py', '.github/workflows/rust-combined-signed-witness.yml',", "'tools/rust_combined_http_materials.py',\n        'crates/latent-component-threading/src/rust_catalogue/combined-corrected-v1/origin.json',\n        '.github/workflows/rust-combined-signed-witness.yml',")
p.write_text(s)
p = root / 'tools/rust_thread_http_combined_node.py'
s = p.read_text().replace('IMPORTS, PROFILE, SOURCE, RUN, WRAPPED', 'IMPORTS, PROFILE, SOURCE, RUN, JOB, ARTIFACT, WRAPPED, ORIGIN')
a = s.index("    require(projection['componentDigest']"); b = s.index('    before = ', a)
s = s[:a] + '    require_current_projection(projection, component)\n' + s[b:]
a = s.index('def run(artifact:')
s = s[:a] + '''def require_current_projection(projection: dict, component: dict) -> None:
    require(projection['componentDigest'] == component['sha256']
            and component == WRAPPED and projection['selectedHostProfile'] == PROFILE
            and projection['compilerSource'] == SOURCE and projection['compilerRun'] == RUN
            and projection['compilerJob'] == JOB and projection['compilerArtifact'] == ARTIFACT
            and projection['compilerRunConclusion'] == ORIGIN['workflowConclusion']
            and projection['compilerJobConclusion'] == ORIGIN['producerJobConclusion']
            and projection['compilerWorkflowSource'] == ORIGIN['workflowSource']
            and projection['compilerObservationStatus'] == ORIGIN['compilerObservationStatus']
            and projection['applicationRecompiled'] is True
            and projection['applicationRecompiledDuringAssembly'] is False
            and projection['originalCompilerObservationRewritten'] is False
            and projection['normalRustBuilderRouteOpened'] is False,
            'rust-combined-current-compiler-projection')


''' + s[a:]
p.write_text(s)
p = root / 'tools/rust_combined_http_materials.py'
s = p.read_text().replace('"""Retrieve six exact public members of the retained failed combined compiler run."""', '''"""Retrieve exact members from the source-captured corrected compiler job.

The selected compiler job passed. Its ancillary source-check job failed; the
workflow result is retained separately and is never relabelled as a pass.
"""''')
s = s.replace('SOURCE, RUN, JOB, ARTIFACT, PINS', 'SOURCE, RUN, JOB, ARTIFACT, PINS, ORIGIN')
a = s.index('ARCHIVE ='); b = s.index('PREFIX =', a)
s = s[:a] + "ARCHIVE = ORIGIN['archive']\n" + s[b:]
a = s.index('    require(run['); b = s.index('    output = fresh(output)', a)
s = s[:a] + '''    require(run['id'] == RUN and run['path'] == ORIGIN['workflowPath']
            and run['event'] == 'push' and run['head_sha'] == ORIGIN['workflowSource']
            and run['run_attempt'] == 1 and run['head_branch'] == ORIGIN['workflowBranch']
            and run['status'] == 'completed' and run['conclusion'] == ORIGIN['workflowConclusion']
            and job['id'] == JOB and job['run_id'] == RUN
            and job['head_sha'] == ORIGIN['workflowSource'] and job['name'] == ORIGIN['jobName']
            and job['status'] == 'completed' and job['conclusion'] == ORIGIN['producerJobConclusion'],
            'rust-combined-exact-compiler-job-identity')
    artifact = api(f'actions/artifacts/{ARTIFACT}')
    require(all(artifact.get(name) == value for name, value in ARCHIVE.items())
            and artifact['name'] == ORIGIN['artifactName']
            and artifact['expired'] is False and artifact['workflow_run']['id'] == RUN
            and artifact['workflow_run']['head_sha'] == ORIGIN['workflowSource']
            and artifact['workflow_run']['repository_id'] == artifact['workflow_run']['head_repository_id'] == 1337591365,
            'rust-combined-exact-compiler-artifact')
''' + s[b:]
s = s.replace('len(rows) == 199 and len({row.filename.casefold() for row in rows}) == 199', "len(rows) == ORIGIN['archiveMembers']\n                and len({row.filename.casefold() for row in rows}) == len(rows)")
s = s.replace("'producerConclusion': 'failure'", "'producerConclusion': ORIGIN['producerJobConclusion'],\n        'workflowSource': ORIGIN['workflowSource'], 'workflowConclusion': ORIGIN['workflowConclusion']")
s = s.replace("'applicationRecompiled': False", "'applicationRecompiled': True, 'applicationRecompiledDuringRetrieval': False")
p.write_text(s)
