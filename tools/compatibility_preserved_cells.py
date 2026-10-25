"""ONLY six named passed cells from three exact source epochs; originals never become current execution.

Whole archives and original public unions stay immutable. Exact passive
observer postimages and the default-None Go observer callback are explicitly different; current diagnostic reanalysis is
separate. This module never compiles or invokes a guest.
"""
from pathlib import Path, PurePosixPath
import hashlib
import json
import os
import stat
import sys
import time
import zipfile

if __package__ in {None, ''}: sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_process import run_bounded_result
from tools.compatibility_closure_matrix import read_retained
from tools.dev_workflow.common import require
from tools.java_replay_materials import api
from tools.phase3_resource_identity import file_identity, inventory, source_identity
from tools.rust_capsule_project import ROOT, checked_path, fresh, read_file, read_json, write_json
from tools import compatibility_native_products as native

SOURCE = 'cc8b88b18abda6e03fc3097d8af658f5e16022f6'
RUN = 40219113023
BRANCH = 'feat/sdk-compatibility-closure-20261025'
WORKFLOW = '.github/workflows/compiler-compatibility.yml'
MAX_ARCHIVE = 16 * 1024**2
MAX_EXPANDED = 64 * 1024**2
MAX_FILES = 512
MAX_FILE = 64 * 1024**2
PASSIVE = {
    'tools/guest_compiler_edges.py': {
        'original': {'size': 16978, 'digest': 'sha256:c8c79b0871d3653dca7ed5846e563472155bc08550fc1723c3b7cd306e2ca0b0'},
        'current': {'size': 17163, 'digest': 'sha256:0b351e4ef217471a49649bb515c9970191a5ae1f2da23e8c501d4c0202d9842d'}},
    'tools/guest_emitted_code.py': {
        'original': {'size': 20181, 'digest': 'sha256:211c7ef2b359b2ec2e2227cae1e4212b57c020dc4f02649302c976e0eb85dbbd'},
        'current': {'size': 22393, 'digest': 'sha256:d647d9512d3405666b1d896e67c8e3cc74c35f12d0682d73529e0f6327fbcaae'}}}
PINS = {'java': {'job': 121246619390,
          'artifact': 12608697008,
          'archive': {'bytes': 2437934,
                      'sha256': 'sha256:efbba7f3f9b39fc271a619f7fc4a8f97422a42593bd54c023f87d99f5220427b'},
          'members': 296,
          'expanded': 13350940,
          'admission': {'bytes': 42309,
                        'sha256': 'sha256:c8360ae249ff92875fe869c4ab7627320b4c5a7a15f811377825b6b10ff38bec'},
          'qualified': {'bytes': 139422,
                        'sha256': 'sha256:67cbffae7981e0ef2d3a3d305ad04b451c50810bad675315bb6f2b102c13b4c6'},
          'recipes': {'build/recipe-inputs.json': 77, 'counterfactual-build/recipe-inputs.json': 76},
          'sources': {'build/source-inputs.json': 218, 'counterfactual-build/source-inputs.json': 218}},
 'typescript': {'job': 121246619264,
                'artifact': 12608777468,
                'archive': {'bytes': 12775530,
                            'sha256': 'sha256:f4dfc9aa0ed16043d8f1d31b46e15438bd4ef39c4d5d238e6e240915ff4d597c'},
                'members': 375,
                'expanded': 40079449,
                'admission': {'bytes': 52519,
                              'sha256': 'sha256:00b70da97948b6da87cf74ec2f89eabf19d0d47fe484941762274e9be7e23c2f'},
                'qualified': {'bytes': 99883,
                              'sha256': 'sha256:64f6c3dd692505c47bbc9a75217cae4563f4f585cd286e3711f71492ec2e6e7c'},
                'recipes': {'baseline/recipe-inputs.json': 138},
                'sources': {'baseline/source-inputs.json': 107}},
 'go-queues': {'job': 121246619328,
               'artifact': 12608607713,
               'archive': {'bytes': 4462780,
                           'sha256': 'sha256:fbe3d1e5898528a78950607a7d2e7f2e369612e948ba643152e75d7b6e73326b'},
               'members': 270,
               'expanded': 15901812,
               'admission': {'bytes': 37441,
                             'sha256': 'sha256:115ab46bfae2a4d596e6d9caf3baaea729fbeb1bdd987d31d35400a593caafbf'},
               'qualified': {'bytes': 109704,
                             'sha256': 'sha256:b9985b74f7f417d574f8d0ec00560083bf1f981579d96ac200b24e6eac89ff94'},
               'recipes': {'baseline/recipe-inputs.json': 66},
               'sources': {'baseline/source-inputs.json': 116}}}


SECOND_SOURCE = '723ffc6a304737b000af03ddb65499b30e0a25f4'
SECOND_RUN = 40226045441
# Two fixed historical observer versions, never inferred from a latest run.
PASSIVE_ORIGINALS = {SOURCE: {name: dict(row['original']) for name, row in PASSIVE.items()},
    SECOND_SOURCE: {name: dict(row['current']) for name, row in PASSIVE.items()}}
for name in ('java', 'typescript', 'go-queues'):
    PINS[name].update(source=SOURCE, run=RUN, nativeSource=native.ORIGINAL_SOURCE)
PINS.update({'rust': {'source': '723ffc6a304737b000af03ddb65499b30e0a25f4',
          'run': 40226045441,
          'job': 121267515763,
          'artifact': 12611590450,
          'archive': {'bytes': 4493272,
                      'sha256': 'sha256:8dd4bd6887ff574df6b82fd3ecfa65b78cf32fdf7da97deaa782349cc1598fa6'},
          'members': 331,
          'expanded': 17491081,
          'admission': {'bytes': 47078,
                        'sha256': 'sha256:8a0a079e67c67e7284601bbe4d0ed1df9c1cf1831a65a942b2ae251cee3774f6'},
          'qualified': {'bytes': 205195,
                        'sha256': 'sha256:8eecc7256f669f4e4e6e3e4082e088e1dad1f258afde1b75fd27c26bca26f672'},
          'recipes': {'baseline/recipe-inputs.json': 121,
                      'initializer/recipe-inputs.json': 121,
                      'reached/recipe-inputs.json': 121},
          'sources': {'baseline/source-inputs.json': 65,
                      'initializer/source-inputs.json': 65,
                      'reached/source-inputs.json': 65}},
 'typescript-initializer': {'source': '723ffc6a304737b000af03ddb65499b30e0a25f4',
                            'run': 40226045441,
                            'job': 121267515667,
                            'artifact': 12610629716,
                            'archive': {'bytes': 12835034,
                                        'sha256': 'sha256:92950c1e9d64b52730ca566590288ed1de35ee91f67fb4c23781ddd095d2eabc'},
                            'members': 137,
                            'expanded': 39696943,
                            'admission': {'bytes': 19665,
                                          'sha256': 'sha256:5490f2dd8cfdab0ee66e74f1d87fb6a222a2aa8710beee7535dcef025377433e'},
                            'qualified': {'bytes': 58013,
                                          'sha256': 'sha256:97b7234f79e9d9d99f2b41c4ee011fbb3abb922417c70382e02dbd2d0ff922ae'},
                            'recipes': {'baseline/recipe-inputs.json': 137},
                            'sources': {'baseline/source-inputs.json': 66}}})
for name in ('rust', 'typescript-initializer'):
    PINS[name]['nativeSource'] = native.CLIENT_DATA_SOURCE
PASSIVE['tools/guest_compiler_edges.py']['current'] = {'size': 18746, 'digest': 'sha256:4e3d2a2bc6d96fcd4294bc394e25e49e449607d76f512a1de73d2897dad0eb8f'}


THIRD_SOURCE = '61a0be045ca33f44cd2ae1467e272168bccdafb7'
PINS['c'] = {'source': '61a0be045ca33f44cd2ae1467e272168bccdafb7',
 'run': 40229947914,
 'job': 121279317395,
 'artifact': 12612589311,
 'archive': {'bytes': 5464710,
             'sha256': 'sha256:d6c1fd9cde980742e4f3527eb303a722a6c2649988a04d1b7fe49e75a37f5ef9'},
 'members': 391,
 'expanded': 20301934,
 'admission': {'bytes': 54860,
               'sha256': 'sha256:2169b917d36c1cdc0ededc82b00d1762a194dbf402bb0db19d1bf9e0645e93fd'},
 'qualified': {'bytes': 169247,
               'sha256': 'sha256:0afaf3615b819b2e9e38b52530f57f07ef871741d245f25aca0a95bb6b7d374e'},
 'recipes': {'baseline/recipe-inputs.json': 56,
             'reached/recipe-inputs.json': 56,
             'initializer/recipe-inputs.json': 56},
 'sources': {'baseline/source-inputs.json': 60,
             'reached/source-inputs.json': 60,
             'initializer/source-inputs.json': 60}}
PINS['c']['nativeSource'] = native.CLIENT_DATA_SOURCE
PASSIVE_ORIGINALS[THIRD_SOURCE] = {name: dict(row['current']) for name, row in PASSIVE.items()}
PASSIVE['tools/guest_compiler_edges.py']['current'] = {'size': 19180, 'digest': 'sha256:167de6a71b90f4c2de95440d0578160b3cd5eccce6163ee087c461f0ad436ed8'}
PASSIVE['tools/guest_api_analysis.py'] = {'original': {'digest': 'sha256:6477141c8897de13cd73a1179ae9350ed0f01baa2ec4aa85442dfb7c8c45daba', 'size': 41055}, 'current': {'size': 65520, 'digest': 'sha256:85c7bb29abddbb3ce909889e58c968be120f7ee41dac9f56e47f74d14df11eb5'}}
for version in (SOURCE, SECOND_SOURCE, THIRD_SOURCE):
    PASSIVE_ORIGINALS[version]['tools/guest_api_analysis.py'] = dict(PASSIVE['tools/guest_api_analysis.py']['original'])
# Only the old Go-queue recipe consumes this unchanged-default builder.
# The sole code delta is the private callable/None observer after final checks;
# None preserves original compiler argv and execution, as the source control proves.
GO_OBSERVER_POSTIMAGE = {'original': {'digest': 'sha256:9a5c5b93c66e894791edfb191428908e31da3342d13f02291ee054bc37bea22e', 'size': 13534}, 'current': {'size': 13815, 'digest': 'sha256:be180b784d9c2a854ef4602904ec5dcb57dbb7cb89ebc79e8537f17740e8f61c'}}


def identity(raw):
    return {'bytes': len(raw), 'sha256': 'sha256:' + hashlib.sha256(raw).hexdigest()}


def _name(name):
    path = PurePosixPath(name)
    require(type(name) is str and 0 < len(name.encode()) <= 512 and str(path) == name
        and not path.is_absolute() and '..' not in path.parts and '\\' not in name and ':' not in name,
        'preserved-cell-relative-path')
    return name


def _origin(cell, run, job, artifact):
    pin = PINS[cell]; original_source, original_run = pin['source'], pin['run']
    require(run['id'] == original_run and run['head_sha'] == original_source and run['head_branch'] == BRANCH
        and run['path'] == WORKFLOW and run['event'] == 'push' and run['run_attempt'] == 1
        and run['status'] == 'completed' and run['conclusion'] == 'failure',
        'preserved-cell-original-run')
    # The overall eight-cell run failed. THESE fixed individual jobs passed.
    require(job['id'] == pin['job'] and job['run_id'] == original_run and job['head_sha'] == original_source
        and job['name'] == 'Required finite ' + cell + ' compatibility completion'
        and job['status'] == 'completed' and job['conclusion'] == 'success',
        'preserved-cell-original-successful-job')
    require(artifact['id'] == pin['artifact'] and artifact['size_in_bytes'] == pin['archive']['bytes']
        and artifact['digest'] == pin['archive']['sha256'] and artifact['expired'] is False
        and artifact['name'] == 'compatibility-closure-' + original_source + '-' + cell
        and artifact['workflow_run']['id'] == original_run and artifact['workflow_run']['head_sha'] == original_source
        and artifact['workflow_run']['head_branch'] == BRANCH, 'preserved-cell-original-artifact')


def _archive(path, cell, destination=None):
    """Authenticate a complete fixed ZIP, then all fixed public members/CRCs."""
    pin = PINS[cell]
    require(file_identity(path, MAX_ARCHIVE) == pin['archive'], 'preserved-cell-whole-archive')
    with zipfile.ZipFile(path) as archive:
        rows = archive.infolist()
        names = [row.filename for row in rows]
        require(len(rows) == len(set(names)) == pin['members'] <= MAX_FILES
            and sum(row.file_size for row in rows) == pin['expanded'] <= MAX_EXPANDED,
            'preserved-cell-archive-bounds')
        for row in rows:
            _name(row.filename)
            require(not row.is_dir() and stat.S_IFMT(row.external_attr >> 16) in (0, stat.S_IFREG)
                and not row.flag_bits & 1 and 0 <= row.file_size <= MAX_FILE,
                'preserved-cell-regular-member')
        admission_raw = archive.read('ADMISSION.json')
        require(identity(admission_raw) == pin['admission']
            and identity(archive.read('qualified.json')) == pin['qualified'],
            'preserved-cell-original-receipts')
        admission = json.loads(admission_raw)
        require(type(admission) is dict and type(admission.get('files')) is dict
            and set(names) == set(admission['files']) | {'ADMISSION.json'},
            'preserved-cell-admitted-archive-union')
        if destination is not None: destination = fresh(destination)
        for row in rows:
            raw = archive.read(row)  # zipfile checks the actual member CRC.
            if row.filename != 'ADMISSION.json':
                require(identity(raw) == admission['files'][row.filename],
                    'preserved-cell-admitted-member')
            if destination is not None:
                target = destination / row.filename
                target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                with target.open('xb') as output: output.write(raw)
                target.chmod(0o600)
    return admission


def _input_identity(path):
    row = file_identity(path, 8 * 1024**2)
    return {'digest': row['sha256'], 'size': row['bytes']}


def _equivalence(directory, cell):
    """Only these exact recipe differences are passive diagnostic code changes."""
    recipes, captured, changes = {}, {}, {}
    allowed = dict(PASSIVE)
    if cell == 'go-queues': allowed['tools/go_capsule_build.py'] = GO_OBSERVER_POSTIMAGE
    for name, count in PINS[cell]['recipes'].items():
        rows = read_json(directory / name, 1024**2)
        require(type(rows) is dict and len(rows) == count, 'preserved-cell-original-recipe-count')
        for relative, expected in rows.items():
            _name(relative)
            require(type(expected) is dict and set(expected) == {'digest', 'size'},
                'preserved-cell-recipe-shape')
            current = _input_identity(ROOT / relative)
            if relative in allowed:
                original = (GO_OBSERVER_POSTIMAGE['original'] if relative == 'tools/go_capsule_build.py'
                    else PASSIVE_ORIGINALS[PINS[cell]['source']][relative])
                require(expected == original and current == allowed[relative]['current'],
                    'preserved-cell-exact-passive-postimage')
                changes[relative] = {'original': expected, 'current': current, 'changed': expected != current,
                    'currentDiagnosticsReanalysisRequired': True, 'newRuntimeExecutionClaimed': False}
            else:
                require(current == expected, 'preserved-cell-consumed-recipe-drift')
        recipes[name] = {'files': len(rows), 'inventory': identity(
            (json.dumps(rows, sort_keys=True, separators=(',', ':')) + '\n').encode())}
    require(set(changes) == set(allowed), 'preserved-cell-closed-passive-delta')
    for name, count in PINS[cell]['sources'].items():
        rows = read_json(directory / name, 1024**2)
        require(type(rows) is dict and len(rows) == count, 'preserved-cell-original-source-count')
        bound, app_wit = 0, {}
        for relative, expected in rows.items():
            _name(relative)
            if relative.startswith(('vendor/lsf/sdk/', 'vendor/lsf/wit/')):
                # Literal normal captured source mapping, no basename guessing.
                current = ROOT / relative[len('vendor/lsf/'):]
                require(_input_identity(current) == expected, 'preserved-cell-captured-sdk-wit-drift')
                bound += 1
            elif relative.startswith('wit/'):
                # Generated application WIT belongs to the original capture.
                # A same spelling in some other checkout is not its origin.
                app_wit[relative] = expected
        require(bound > 0 and app_wit, 'preserved-cell-captured-sdk-wit-missing')
        captured[name] = {'currentSDKAndCanonicalWitFiles': bound,
            'originalGeneratedApplicationWit': app_wit, 'originalCaptureInventory': identity(
                (json.dumps(rows, sort_keys=True, separators=(',', ':')) + '\n').encode()),
            'applicationRecaptured': False, 'currentRebuildClaimed': False}
    return {'originalSourceCommit': PINS[cell]['source'], 'recipes': recipes, 'capturedSources': captured,
        'passiveDiagnosticChanges': changes, 'runtimeSourceRelabeled': False,
        'currentDiagnosticResultInferred': False}



AUXILIARY_ROOTS = ('api/proto', 'schemas', 'wit', 'examples/echo-contract/wit')
AUXILIARY_COUNT = 128
AUXILIARY_BYTES = 745908
AUXILIARY_SHA = 'sha256:ffad8cf689f432295751407f84b9d009454f911d2921dbe123a54a4123a5facd'


def _auxiliary(version):
    # Original17e8 source-inputs.json22447B/d9696551 binds this exact128-row
    # compiled auxiliary census. New files are NOT silently outside a path list.
    rows, deadline = {}, time.monotonic() + 30
    for prefix in AUXILIARY_ROOTS:
        observed = inventory(ROOT / prefix, maximum_files=512, maximum_bytes=4*1024**2, deadline=deadline)
        for row in observed['files']:
            name = prefix + '/' + row['path']
            require(name not in rows, 'preserved-cell-native-auxiliary-duplicate')
            rows[name] = {key: row[key] for key in ('bytes', 'sha256')}
    rows['.cargo/managed-guest.toml'] = file_identity(ROOT / '.cargo/managed-guest.toml', 1024**2)
    require(len(rows) == AUXILIARY_COUNT and sum(row['bytes'] for row in rows.values()) <= 4*1024**2,
        'preserved-cell-native-auxiliary-count')
    current = identity((json.dumps(rows, sort_keys=True, separators=(',', ':')) + '\n').encode())
    golden = 'api/proto/phase1-descriptor-contract.json'
    pair = native.NON_COMPILED_DATA[golden]
    require(rows[golden] == pair[version], 'preserved-cell-native-exact-golden')
    rows[golden] = pair['before']  # ONLY the already reviewed noncompiled oracle.
    original = identity((json.dumps(rows, sort_keys=True, separators=(',', ':')) + '\n').encode())
    require(original['sha256'] == AUXILIARY_SHA
        and sum(row['bytes'] for row in rows.values()) == AUXILIARY_BYTES,
        'preserved-cell-native-compiled-auxiliary-drift')
    return {'files': AUXILIARY_COUNT, 'originalBytes': AUXILIARY_BYTES,
        'originalCanonical': original, 'currentCanonical': current,
        'normalizedOnly': [] if version == 'before' else [golden]}


def verify_prepared(output):
    """Offline recheck, including the original ZIPs and original public union."""
    output = checked_path(Path(output))
    require({path.name for path in output.iterdir()} == {'archives', *PINS},
        'preserved-cell-exact-prepared-roots')
    archives = output / 'archives'
    require(archives.is_dir() and not archives.is_symlink()
        and {path.name for path in archives.iterdir()} == {*('run-' + pin['source'] + '.json' for pin in PINS.values()),
            *(cell + suffix for cell in PINS for suffix in ('.zip', '-job.json', '-artifact.json'))},
        'preserved-cell-exact-archive-roots')
    records, equivalence = {}, {}
    # Same immutable explicit native source scope accepted by the normal reader.
    current_native = source_identity(ROOT)
    require(current_native in (native.ORIGINAL_SOURCE, native.CLIENT_DATA_SOURCE),
        'preserved-cell-current-native-inputs')
    version = 'before' if current_native == native.ORIGINAL_SOURCE else 'after'
    for name, pair in native.NON_COMPILED_DATA.items():
        require(file_identity(ROOT / name, 8 * 1024**2) == pair[version],
            'preserved-cell-current-native-noncompiled-data')
    auxiliary = _auxiliary(version)
    for cell in PINS:
        run = read_json(archives / ('run-' + PINS[cell]['source'] + '.json'), 1024**2)
        _origin(cell, run, read_json(archives / (cell + '-job.json'), 1024**2),
            read_json(archives / (cell + '-artifact.json'), 1024**2))
        _archive(archives / (cell + '.zip'), cell)
        directory = output / cell
        require(file_identity(directory / 'ADMISSION.json', 4 * 1024**2) == PINS[cell]['admission']
            and file_identity(directory / 'qualified.json', 4 * 1024**2) == PINS[cell]['qualified'],
            'preserved-cell-original-extracted-receipts')
        record = read_retained(directory)
        require(record['sourceCommit'] == PINS[cell]['source'] and record['cell'] == cell and record['status'] == 'passed'
            and record['wholeTicketComplete'] is False and record['nativeBuildCount'] == 0
            and record['native']['compiledSource'] == native.QUALIFIED['source']
            and record['native']['producerRun'] == native.QUALIFIED['run']
            and record['native']['producerJob'] == native.QUALIFIED['job']
            and record['native']['origin']['artifact'] == native.QUALIFIED['artifact']['id']
            and record['native']['origin']['archiveDigest'] == native.QUALIFIED['artifact']['digest']
            and record['nativeSource'] == PINS[cell]['nativeSource'], 'preserved-cell-original-qualification')
        records[cell] = record
        equivalence[cell] = {**_equivalence(directory, cell), 'originalRun': PINS[cell]['run'],
            'originalJob': PINS[cell]['job'], 'originalArtifact': PINS[cell]['artifact'],
            'wholeArchive': PINS[cell]['archive'], 'currentExplicitNativeSource': current_native,
            'nativeSourceScopeHermetic': False, 'currentNativeBuildClaimed': False,
            'compiledAuxiliaryInputs': auxiliary,
            'originalNativeProducts': record['native']['products']}
    return {'records': records, 'sourceEquivalence': equivalence}


def prepare(output):
    """One fixed acquisition of six already successful public evidence ZIPs."""
    output = fresh(Path(output)); archives = fresh(output / 'archives')
    runs = {}
    for cell, pin in PINS.items():
        if pin['run'] not in runs:
            runs[pin['run']] = api('actions/runs/' + str(pin['run']))
            write_json(archives / ('run-' + pin['source'] + '.json'), runs[pin['run']])
        run = runs[pin['run']]
        job = api('actions/jobs/' + str(pin['job']))
        artifact = api('actions/artifacts/' + str(pin['artifact']))
        _origin(cell, run, job, artifact)
        write_json(archives / (cell + '-job.json'), job)
        write_json(archives / (cell + '-artifact.json'), artifact)
        downloaded = run_bounded_result(['gh', 'api', 'repos/KirilsTurkins/latent-service-fabric/actions/artifacts/'
            + str(pin['artifact']) + '/zip'], cwd=ROOT, env=dict(os.environ),
            timeout_seconds=115, max_output_bytes=MAX_ARCHIVE)
        require(downloaded.returncode == 0 and identity(downloaded.stdout) == pin['archive'],
            'preserved-cell-fixed-download')
        path = archives / (cell + '.zip'); path.write_bytes(downloaded.stdout)
        _archive(path, cell, output / cell)
    return verify_prepared(output)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    prepare(parser.parse_args().output)
