"""Hosted reconstruction of ONE pinned completed low-level normal library.

No engine envelope reuse, receipt rewriting, Mach fallback or cache search.
The shared original normal validator is mandatory before any feature build.
"""
import json
import hashlib
import stat
import os
from pathlib import Path, PurePosixPath
import shutil
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

from tools import typescript_borrow_retry_inputs as producer
from tools.java_replay_materials import api, NoRedirect
from tools.phase3_resource_identity import file_identity
from tools.build_observation import build_environment
from tools.rust_capsule_project import ROOT, digest, read_file, write_json
from tools.typescript_guest import native_build, promise_library


def require(value, reason):
    if not value: raise ValueError(reason)


def library_member(name: str) -> str:
    prefix=producer.PREFIX+'library/'
    require(name.startswith(prefix),'own-library-member-prefix')
    relative=name[len(prefix):];path=PurePosixPath(relative)
    require(relative and str(path)==relative and not path.is_absolute()
            and all(part not in ('','.','..') for part in relative.split('/'))
            and ':' not in relative and '\\' not in relative,'own-library-member-path')
    return relative


def archive_objects(path: Path, wanted: dict, deadline: float, maximum: int) -> tuple[dict,dict]:
    """Read real AR members by original size/hash, including identical duplicates.

    No object execution or guessed archive ordinal. Conflicting candidates are
    refused even when another candidate would match the requested identity.
    """
    require(path.is_file() and not path.is_symlink(),'own-library-ar-file')
    require(0<len(wanted)<=64 and sum(row['bytes'] for row in wanted.values())<=16*1024**2,
            'own-library-ar-wanted-bound')
    selected={};observed={name:0 for name in wanted};by_name={}
    for name,row in wanted.items():
        relative=PurePosixPath(name)
        require(str(relative)==name and not relative.is_absolute() and '..' not in relative.parts
                and type(row['bytes']) is int and 0<row['bytes']<=16*1024**2
                and re.fullmatch(r'sha256:[0-9a-f]{64}',row['sha256']) is not None,'own-library-ar-object-identity')
        by_name.setdefault(relative.name,[]).append(name)
    with path.open('rb') as source:
        before=os.fstat(source.fileno());total=before.st_size
        require(8<=total<=maximum and source.read(8)==b'!<arch>\n','own-library-ar-container')
        long_names=b'';members=0
        while source.tell()<total:
            require(time.monotonic()<deadline and members<8192,'own-library-ar-reader-bound')
            header=source.read(60);members+=1
            require(len(header)==60 and header[58:]==b'`\n' and header[48:58].strip().isdigit(),
                    'own-library-ar-header')
            size=int(header[48:58]);start=source.tell();end=start+size
            require(end+(size%2)<=total,'own-library-ar-member-size')
            raw_name=header[:16].decode('ascii').strip();name=raw_name;payload=size
            if raw_name=='//':
                require(size<=4*1024**2,'own-library-ar-long-name-bound');long_names=source.read(size)
            elif raw_name in ('/','/SYM64/'):
                pass
            else:
                if raw_name.startswith('#1/'):
                    require(raw_name[3:].isdigit(),'own-library-ar-bsd-name')
                    width=int(raw_name[3:]);require(0<width<=4096 and width<=size,'own-library-ar-bsd-name-bound')
                    name=source.read(width).rstrip(b'\0').decode('ascii');payload-=width
                elif raw_name.startswith('/'):
                    require(raw_name[1:].isdigit(),'own-library-ar-name-offset')
                    offset=int(raw_name[1:]);require(0<=offset<len(long_names),'own-library-ar-name-offset')
                    stop=long_names.find(b'/\n',offset)
                    require(offset<stop<=offset+4096,'own-library-ar-long-name')
                    name=long_names[offset:stop].decode('ascii')
                else:name=raw_name.removesuffix('/')
                targets=by_name.get(PurePosixPath(name).name,[])
                if targets:
                    require(all(wanted[target]['bytes']==payload for target in targets),'own-library-ar-conflicting-size')
                    raw=source.read(payload);require(len(raw)==payload,'own-library-ar-truncated-object')
                    identity={'bytes':len(raw),'sha256':digest(raw)}
                    for target in targets:
                        require(identity==wanted[target],'own-library-ar-conflicting-identity')
                        if target in selected:require(selected[target]==raw,'own-library-ar-conflicting-duplicate')
                        else:selected[target]=raw
                        observed[target]+=1
            source.seek(end+(size%2))
        after=os.fstat(source.fileno())
        require((before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns)==
                (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns),'own-library-ar-changed')
    require(set(selected)==set(wanted) and time.monotonic()<deadline,'own-library-ar-missing-object')
    return selected,{'members':members,'matchingMembers':observed}


def download(output: Path, deadline: float) -> Path:
    producer.metadata(api('actions/runs/'+str(producer.RUN)),api('actions/jobs/'+str(producer.JOB)),
                      api('actions/artifacts/'+str(producer.ARTIFACT)))
    token=os.environ.get('GH_TOKEN')
    require(isinstance(token,str) and 0<len(token)<=4096,'own-library-read-token')
    request=urllib.request.Request('https://api.github.com/repos/KirilsTurkins/latent-service-fabric/actions/artifacts/'+str(producer.ARTIFACT)+'/zip',
                                  headers={'Authorization':'Bearer '+token})
    try: urllib.request.build_opener(NoRedirect).open(request,timeout=30)
    except urllib.error.HTTPError as error:
        require(error.code==302,'own-library-artifact-redirect');location=error.headers['Location']
    else: raise ValueError('own-library-redirect-required')
    parsed=urllib.parse.urlsplit(location)
    require(parsed.scheme=='https' and parsed.username is None and parsed.hostname is not None
            and (parsed.hostname.endswith('.blob.core.windows.net') or parsed.hostname.endswith('.githubusercontent.com')),
            'own-library-artifact-origin')
    archive=output/'producer.zip';count=0;expires=min(deadline,time.monotonic()+180)
    with urllib.request.urlopen(location,timeout=90) as response,archive.open('xb') as target:
        while block:=response.read(1024**2):
            count+=len(block);require(count<=producer.ARCHIVE_BYTES and time.monotonic()<expires,'own-library-acquisition-bound')
            target.write(block)
    require(file_identity(archive,producer.ARCHIVE_BYTES)=={'bytes':producer.ARCHIVE_BYTES,
            'sha256':'sha256:'+producer.ARCHIVE_SHA},'own-library-original-archive-identity')
    return archive


def reconstruct(output: Path, run, deadline: float) -> tuple[Path,dict]:
    """Invoked only by the hosted owner after explicit programme review."""
    output.mkdir(exist_ok=False)
    archive=download(output,deadline)
    library=output/'library';library.mkdir()
    material=output/'original-material';material.mkdir()
    with zipfile.ZipFile(archive) as zipped:
        # Reuse the exact immutable producer metadata, paths/bounds and ALL-CRC
        # checks. This reader never validates/rebinds its old SDK engine input.
        producer.selected_members(zipped)
        compilation=json.loads(zipped.read(producer.ENGINE+'engine-compilation.json'))
        names=[row.filename for row in zipped.infolist() if row.filename.startswith(producer.PREFIX+'library/')]
        require(0<len(names)<=8192,'own-library-member-count')
        for name in names:
            require(time.monotonic()<deadline,'own-library-extraction-deadline')
            target=library/library_member(name);target.parent.mkdir(parents=True,exist_ok=True)
            with zipped.open(name) as source,target.open('xb') as sink:shutil.copyfileobj(source,sink,1024**2)
        # Restore only exact normal materializer headers. Retained engine header
        # bytes are source facts, not a new claim about that historical engine.
        for name,identity in compilation['installedHeaders'].items():
            path=PurePosixPath(name)
            require(str(path)==name and not path.is_absolute() and '..' not in path.parts,'own-library-header-path')
            raw=zipped.read(producer.ENGINE+'spidermonkey/include/'+name)
            require({'bytes':len(raw),'sha256':digest(raw)}==identity,'own-library-retained-header-identity')
            target=library/'obj/dist/include'/name
            if target.exists():require(read_file(target)==raw,'own-library-existing-header-differs')
            else:target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
        combined=material/'combined.a'
        with zipped.open(producer.ENGINE+'spidermonkey/libspidermonkey.a') as source,combined.open('xb') as sink:
            shutil.copyfileobj(source,sink,1024**2)
        require(file_identity(combined,compilation['archiveCompositionLimits']['maximumCombinedBytes'])==compilation['combinedLibrary'],
                'own-library-original-combined-identity')
    receipt=json.loads(read_file(library/'library-build.json'))
    original_receipt=read_file(library/'library-build.json')
    acquisitions={}
    for name,pin in promise_library.SOURCES.items():
        acquisitions[name]=promise_library.acquire(library/(name+'.archive'),pin,deadline)
        # Keep retained original acquisition receipts byte-identical. If the
        # producer omitted one, its actual new fixed acquisition is recorded.
        target=library/(name+'-acquisition.json')
        if not target.exists():write_json(target,acquisitions[name])
    wasi=promise_library.extract(library/'wasi-sdk.archive',library/'wasi-source',
        'wasi-sdk-30.0-x86_64-linux',deadline=deadline)
    shutil.copyfile(library/'cbindgen.archive',library/'cbindgen');(library/'cbindgen').chmod(0o700)
    hook=receipt['exportedHeader'];relative=PurePosixPath(hook['resolvedPath'])
    require(not relative.is_absolute() and str(relative)==hook['resolvedPath'] and '..' not in relative.parts,
            'own-library-hook-target')
    exported=library/hook['path'];raw=read_file(exported)
    require(raw==read_file(ROOT/'sdk/typescript-guest/activation/promise_hooks.h'),'own-library-original-hook-bytes')
    resolved=library/relative;resolved.parent.mkdir(parents=True,exist_ok=True)
    if resolved.exists():require(read_file(resolved)==raw,'own-library-existing-hook-target')
    else:resolved.write_bytes(raw)
    exported.unlink();exported.symlink_to(os.path.relpath(resolved,exported.parent))
    confdefs=library/'obj/js/src/js-confdefs.h';confdefs.parent.mkdir(parents=True,exist_ok=True)
    confdefs.write_bytes(read_file(library/'obj/dist/include/js-confdefs.h'))
    require(file_identity(confdefs)==compilation['installedHeaders']['js-confdefs.h'],'own-library-confdefs-identity')
    objects=compilation['supportingObjects']
    native_build.combined_archive_limits(compilation['libraryProduct'],objects)
    # Frozen original normal-compilation identities authenticate every object;
    # the fresh normal engine independently rechecks its unchanged CMake list.
    selected,selection=archive_objects(combined,objects,deadline,compilation['archiveCompositionLimits']['maximumCombinedBytes'])
    for name,identity in objects.items():
        path=PurePosixPath(name)
        require(not path.is_absolute() and str(path)==name and '..' not in path.parts and ':' not in name,
                'own-library-supporting-object-path')
        raw=selected[name]
        require({'bytes':len(raw),'sha256':digest(raw)}==identity,'own-library-supporting-object-identity')
        target=library/'obj'/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
    # The same normal source validator used by native_build MUST pass now.
    normal=native_build.validated_library(library)
    require(read_file(library/'library-build.json')==original_receipt,'own-library-original-receipt-edited')
    require(time.monotonic()<deadline,'own-library-final-deadline')
    record={'schemaVersion':'latent.typescript.own-library-reconstruction.v1','status':'passed',
            'producer':{'head':producer.HEAD,'run':producer.RUN,'job':producer.JOB,'artifact':producer.ARTIFACT,
                        'conclusion':'failure; completed normal library only'},
            'producerArchive':file_identity(archive,producer.ARCHIVE_BYTES),'originalLibraryReceipt':file_identity(library/'library-build.json'),
            'originalLibrary':normal[2],'restoredSupportingObjects':objects,'originalMemberSelection':selection,
            'libraryRecipeEquivalences':{name:proof for name,identity in normal[0]['recipe'].items()
                if (proof := native_build.library_recipe_equivalence(name,read_file(ROOT/name),identity)) is not None},
            'newFixedAcquisitions':acquisitions,'normalValidatorPassed':True,
            'engineReused':False,'receiptReissued':False,'machBuildCount':0,'firefoxExtracted':False}
    write_json(output/'LIBRARY-RECONSTRUCTION.json',record)
    return library,record


# ONE completed preparation prefix, not a generic cache or successful producer.
PREPARED_HEAD = '9c626d3b2903037cdc157c7d736246afec9b8a0e'
PREPARED_TREE = '81807f797f8e6dc096656677278198a93b00a2d6'
PREPARED_RUN = 40879155085
PREPARED_JOB = 123465708129
PREPARED_ARTIFACT = 12899599715
PREPARED_BYTES = 196361015
PREPARED_SHA = '9df6d958d5e5364c6d7c8d985d38bace3eea46d96ada26ea6b5ac9bf5ae4ac62'
PREPARED_EXPANDED = 576897486
PREPARED_BRANCH = 'refs/heads/feat/sdk-745-partial-own-20261029'
PREPARED_PREFIX = (
    'source-commit','source-tree','source-clean','node-version','fresh-splicer',
    'partial-rust-0','partial-rust-1','partial-source-controls','fresh-engine',
    'support-rustc-path','support-cargo-path','support-rustc-version','support-cargo-version',
    'support-cargo','support-wrapper','support-wasi-signal','support-wasi-process-clocks',
    'support-wasi-getpid','own-compile-controls','own-link-controls','validate-native-core',
)
PREPARED_FAILED_CASE = 'partial-own-transfer-reuse-and-ACK-refusal'
# These are NEW CONSUMER sources, never compiled engine/splicer/ABI exceptions.
PREPARED_CONSUMER = frozenset((
    'tools/typescript_guest/owned_result_library.py','tools/typescript_guest/owned_result_controls.py',
    'tools/qualify_typescript_owned_results.py','.github/workflows/typescript-owned-results.yml',
    'tools/tests/test_typescript_owned_controls.py',
))
PREPARED_FIXTURE = 'sdk/typescript-guest/activation/tests/native_imports.cpp'


def prepared_metadata(run: dict, job: dict, artifact: dict) -> None:
    require(run.get('id') == PREPARED_RUN and run.get('head_sha') == PREPARED_HEAD
        and run.get('path') == '.github/workflows/typescript-owned-results.yml'
        and run.get('event') == 'push' and run.get('status') == 'completed'
        and run.get('conclusion') == 'failure', 'prepared-original-run')
    require(job.get('id') == PREPARED_JOB and job.get('run_id') == PREPARED_RUN
        and job.get('head_sha') == PREPARED_HEAD and job.get('status') == 'completed'
        and job.get('conclusion') == 'failure', 'prepared-original-job')
    origin = artifact.get('workflow_run', {})
    require(artifact.get('id') == PREPARED_ARTIFACT and artifact.get('expired') is False
        and artifact.get('size_in_bytes') == PREPARED_BYTES
        and artifact.get('digest') == 'sha256:' + PREPARED_SHA
        and origin.get('id') == PREPARED_RUN and origin.get('head_sha') == PREPARED_HEAD,
        'prepared-original-artifact')


def prepared_recipe(rows: dict, expected) -> None:
    require(type(rows) is dict and set(rows) == set(expected), 'prepared-recipe-inventory')
    require(all(file_identity(ROOT / name) == row for name, row in rows.items()),
        'prepared-current-compiled-source-drift')


def prepared_prefix(value: dict) -> None:
    require(value.get('schemaVersion') == 'latent.typescript.partial-own-prerequisites.v2'
        and value.get('status') == 'failed' and value.get('stage') == 'actual-native-cases'
        and value.get('reason') == 'own-controls-command-failed:' + PREPARED_FAILED_CASE
        and value.get('sourceCommit') == PREPARED_HEAD and value.get('sourceTree') == PREPARED_TREE
        and value.get('privateImportBindingAbi') == 2 and value.get('qualification') == 'unknown'
        and value.get('apiSupport') == 'not-evaluated' and value.get('nativeRows') == [],
        'prepared-failed-producer-boundary')
    require(all(value.get(name) is False for name in ('canonicalOwnComponentExecuted','tableReuseQualified',
        'signedExecution','physicalProviderQualified','wholeCostQualification')),
        'prepared-no-producer-qualification')
    commands = value.get('commands')
    require(type(commands) is list and len(commands) == 22
        and [row.get('label') for row in commands] == list(PREPARED_PREFIX) + [PREPARED_FAILED_CASE]
        and all(type(row.get('returncode')) is int and row['returncode'] == 0 for row in commands[:-1])
        and type(commands[-1].get('returncode')) is int and commands[-1]['returncode'] == 10,
        'prepared-exact-21-zero-plus-failed-native')
    origin = value.get('workflowOrigin', {})
    require(origin.get('GITHUB_REPOSITORY') == 'KirilsTurkins/latent-service-fabric'
        and origin.get('GITHUB_SHA') == PREPARED_HEAD and origin.get('GITHUB_WORKFLOW_SHA') == PREPARED_HEAD
        and origin.get('GITHUB_RUN_ID') == str(PREPARED_RUN) and origin.get('GITHUB_EVENT_NAME') == 'push'
        and origin.get('GITHUB_REF') == PREPARED_BRANCH, 'prepared-source-workflow')


def prepared_download(output: Path, deadline: float, run) -> Path:
    token = os.environ.get('GH_TOKEN')
    require(isinstance(token, str) and 0 < len(token) <= 4096, 'prepared-read-token')
    metadata_environment = dict(build_environment(output), GH_TOKEN=token)
    records = []
    for label,path in [('run','actions/runs/'+str(PREPARED_RUN)),
                       ('job','actions/jobs/'+str(PREPARED_JOB)),
                       ('artifact','actions/artifacts/'+str(PREPARED_ARTIFACT))]:
        require(deadline-time.monotonic() > 35, 'prepared-metadata-deadline')
        records.append(json.loads(run('prepared-'+label+'-metadata','gh','api',
            '-H','Cache-Control: no-cache','repos/KirilsTurkins/latent-service-fabric/'+path,
            seconds=30,env=metadata_environment)))
    prepared_metadata(*records)
    expires = min(deadline, time.monotonic()+180)
    require(expires-time.monotonic() > 31, 'prepared-acquisition-deadline')
    request = urllib.request.Request('https://api.github.com/repos/KirilsTurkins/latent-service-fabric/actions/artifacts/'
        +str(PREPARED_ARTIFACT)+'/zip', headers={'Authorization':'Bearer '+token})
    try: urllib.request.build_opener(NoRedirect).open(request, timeout=30)
    except urllib.error.HTTPError as error:
        require(error.code == 302, 'prepared-artifact-redirect')
        location = error.headers['Location']
    else: raise ValueError('prepared-redirect-required')
    parsed = urllib.parse.urlsplit(location)
    require(parsed.scheme == 'https' and parsed.username is None and parsed.hostname is not None
        and (parsed.hostname.endswith('.blob.core.windows.net') or parsed.hostname.endswith('.githubusercontent.com')),
        'prepared-artifact-origin')
    archive = output/'producer.zip'
    require(expires-time.monotonic() > 31, 'prepared-acquisition-deadline')
    with urllib.request.urlopen(location, timeout=30) as source, archive.open('xb') as target:
        size = 0
        while True:
            require(expires-time.monotonic() > 30, 'prepared-acquisition-deadline')
            block = source.read(1024**2)
            if not block: break
            size += len(block)
            require(size <= PREPARED_BYTES, 'prepared-acquisition-size')
            target.write(block)
    require(file_identity(archive, PREPARED_BYTES) == {'bytes':PREPARED_BYTES,'sha256':'sha256:'+PREPARED_SHA},
        'prepared-original-archive-identity')
    return archive


def prepared_extract(archive: Path, output: Path, deadline: float) -> tuple[Path, dict]:
    """All547 safe regular members and CRCs; no body is executed or imported."""
    output.mkdir()
    inventory = {}
    with zipfile.ZipFile(archive) as zipped:
        entries = zipped.infolist()
        require(len(entries) == 547 and sum(row.file_size for row in entries) == PREPARED_EXPANDED,
            'prepared-archive-count-and-total')
        names = set()
        for row in entries:
            name = row.filename; path = PurePosixPath(name)
            require(str(path) == name and not path.is_absolute() and ':' not in name and '\\' not in name
                and all(part not in ('','.','..') for part in name.split('/'))
                and all(32 <= ord(c) < 127 for c in name) and name.casefold() not in names
                and stat.S_ISREG(row.external_attr >> 16) and not row.is_dir() and not row.flag_bits & 1
                and row.compress_type in (zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED)
                and 0 <= row.file_size <= 512*1024**2+16*1024**2+4*1024**2,
                'prepared-safe-member')
            names.add(name.casefold())
        require(all('/'.join(name.split('/')[:i]).casefold() not in names
            for name in (r.filename for r in entries) for i in range(1,len(name.split('/')))),
            'prepared-file-directory-alias')
        for row in entries:
            target = output/row.filename; target.parent.mkdir(parents=True,exist_ok=True)
            actual = hashlib.sha256(); size = 0
            with zipped.open(row) as source, target.open('xb') as sink:
                while True:
                    require(time.monotonic() < deadline, 'prepared-extraction-deadline')
                    block = source.read(1024**2)
                    if not block: break # ZipExtFile has checked the actual CRC at EOF.
                    size += len(block); require(size <= row.file_size, 'prepared-member-size')
                    actual.update(block); sink.write(block)
            require(size == row.file_size, 'prepared-member-truncated')
            inventory[row.filename] = {'bytes':size,'sha256':'sha256:'+actual.hexdigest()}
    require(time.monotonic() < deadline, 'prepared-final-extraction-deadline')
    return output, inventory


def prepared_fixture(output: Path, deadline: float, run, recipe_paths, rust_cases, python_cases) -> tuple:
    """Consume the actual completed prefix, leaving all original receipts intact."""
    from tools.typescript_guest import activation_engine, runtime_profile
    output.mkdir()
    archive = prepared_download(output, deadline, run)
    tree, inventory = prepared_extract(archive, output/'retained', deadline)
    def value(name): return json.loads(read_file(tree/name))
    original = value('FAILED.json'); prepared_prefix(original)
    require(set(original['recipe']) == set(recipe_paths), 'prepared-original-recipe-set')
    unchanged = set(recipe_paths) - PREPARED_CONSUMER - {PREPARED_FIXTURE}
    prepared_recipe({n:original['recipe'][n] for n in unchanged}, unchanged)
    # The compiled inputs have NO consumer exceptions. Their exact current
    # recipe sets and all ABI/SDK rows are independently checked below.
    for row in original['commands']:
        label=row['label']; saved=value(label+'.result.json')
        require(saved == {k:v for k,v in row.items() if k != 'label'}, 'prepared-command-result')
        for stream in ('stdout','stderr'):
            require(file_identity(tree/(label+'.'+stream+'.log')) == row[stream], 'prepared-command-stdio')
        require(type(value(label+'.command.json').get('argv')) is list, 'prepared-command-argv')
    require(read_file(tree/'source-commit.stdout.log').decode().strip() == PREPARED_HEAD
        and read_file(tree/'source-tree.stdout.log').decode().strip() == PREPARED_TREE
        and not read_file(tree/'source-clean.stdout.log').strip(), 'prepared-original-source-commands')
    require(original['actualRustCases'] == list(rust_cases) and original['selectedPythonCases'] == list(python_cases)
        and original['sourceControls'] == {'testsRun':19,'skipped':0,'failures':0,'errors':0}
        and all(type(v) is int for v in original['sourceControls'].values()), 'prepared-prior-source-cases')
    for i,case in enumerate(rust_cases):
        raw=read_file(tree/('partial-rust-'+str(i)+'.stdout.log')).decode()
        require(re.findall(r'^test (lsf_async(?:_splice)?::tests::[A-Za-z0-9_]+) \.\.\. ok$',raw,re.MULTILINE) == [case]
            and re.search(r'test result: ok\. 1 passed; 0 failed; 0 ignored;',raw) is not None,
            'prepared-actual-rust-case')
    require(json.loads(read_file(tree/'partial-source-controls.stdout.log')) == original['sourceControls'],
        'prepared-actual-source-result')
    for name,pin in original['actualGeneratedBindings'].items():
        require(name in ('partial-bindings.js','partial-bindings.zero.js') and
            file_identity(tree/name,256*1024) == pin,'prepared-actual-generated-bindings')
    require(set(original['actualGeneratedBindings']) == {'partial-bindings.js','partial-bindings.zero.js'},
        'prepared-generated-binding-set')
    splicer=tree/'splicer'; source_splicer=native_build.source_splicer(splicer)
    require(source_splicer == original['splicer'], 'prepared-original-splicer')
    engine=tree/'engine'; built=value('engine/engine-build.json'); compiled=value('engine/engine-compilation.json')
    require(built.get('schemaVersion') == 'latent.typescript.native-engine-source-build.v1'
        and built.get('status') == 'passed' and compiled.get('status') == 'core-compiled'
        and built.get('qualification') == compiled.get('qualification') == 'unknown'
        and built.get('apiSupport') == compiled.get('apiSupport') == 'not-evaluated'
        and built.get('sourceSplicer') == compiled.get('sourceSplicer') == source_splicer,
        'prepared-completed-engine')
    engine_paths=('tools/build_typescript_native_engine.py','tools/typescript_guest/native_build.py',
        *activation_engine.engine_input_paths(runtime_profile.IMPORT_PROFILE))
    prepared_recipe(built['recipe'],engine_paths)
    require(compiled['recipe'] == built['recipe'], 'prepared-engine-compilation-recipe')
    for name,pin in original['engineProducts'].items():
        require(name in ('engine.wasm','engine-input.json','engine-build.json','engine-compilation.json','source-derivation.json')
            and file_identity(engine/name,64*1024**2) == pin, 'prepared-engine-products')
    require(set(original['engineProducts']) == {'engine.wasm','engine-input.json','engine-build.json',
        'engine-compilation.json','source-derivation.json'}, 'prepared-engine-product-set')
    envelope=value('engine/engine-input.json'); core=read_file(engine/'engine.wasm',64*1024**2)
    sdk={name:read_file(ROOT/name) for name in activation_engine.engine_input_paths(runtime_profile.IMPORT_PROFILE)}
    runtime_profile.validate_engine(envelope,core,sdk,read_file(ROOT/'wit/platform/activation-runtime/package.wit'),
        profile=runtime_profile.IMPORT_PROFILE)
    require(envelope['sourceDerivationDigest'] == digest(read_file(engine/'source-derivation.json'))
        and envelope['buildReceiptDigest'] == digest(read_file(engine/'engine-compilation.json'))
        and envelope['compilerSplicerInputDigest'] == source_splicer['inputDigest']
        and built['input'] == file_identity(engine/'engine-input.json')
        and built['engine'] == file_identity(engine/'engine.wasm',64*1024**2), 'prepared-engine-receipts')
    headers=built['installedHeaders']
    require(len(headers) == 353 and {n.removeprefix('engine/spidermonkey/include/') for n in inventory
        if n.startswith('engine/spidermonkey/include/')} == set(headers), 'prepared-all-headers')
    for name,pin in headers.items():
        require(inventory['engine/spidermonkey/include/'+name] == pin, 'prepared-header-identity')
    bound=native_build.combined_archive_limits(built['libraryProduct'],built['supportingObjects'])
    require(bound == built['archiveCompositionLimits'] == compiled['archiveCompositionLimits']
        and built['combinedLibrary'] == compiled['combinedLibrary']
        and file_identity(engine/'spidermonkey/libspidermonkey.a',bound['maximumCombinedBytes']) == built['combinedLibrary'],
        'prepared-composed-library')
    support=value('normal-support/SUPPORT.json')
    require(support == original['normalSupport'] and support['status'] == 'passed'
        and support['qualification'] == 'unknown' and support['apiSupport'] == 'not-evaluated'
        and support['sourceAcquisition'] == {k:native_build.SOURCES['starling'][k] for k in ('bytes','sha256')},
        'prepared-original-support')
    relative={'library':'normal-support/target/wasm32-wasip1/release/librust_staticlib.a',
        'wrapper':'normal-support/rust-hooks-wrappers.o'}
    relocated={name:tree/path for name,path in relative.items()}
    for name,path in relative.items():
        require(support['products'][name] == '/home/runner/work/_temp/typescript-own-controls/'+path
            and file_identity(tree/path,64*1024**2 if name == 'library' else 1024**2) == support[name],
            'prepared-support-product')
    for name,pin in support['manifest'].items():
        require(name in ('Cargo.toml','Cargo.lock','rust-staticlib.rs') and
            file_identity(tree/'normal-support/rust-staticlib'/name) == pin, 'prepared-support-manifest')
    require(set(support['manifest']) == {'Cargo.toml','Cargo.lock','rust-staticlib.rs'}, 'prepared-support-manifest-set')
    proof={'schemaVersion':'latent.typescript.prepared-partial-fixture-input.v1',
        'producer':{'head':PREPARED_HEAD,'tree':PREPARED_TREE,'run':PREPARED_RUN,'job':PREPARED_JOB,
            'artifact':PREPARED_ARTIFACT,'status':'failed-at-first-native-case','commandsZero':21,'commandsFailed':1},
        'archive':file_identity(archive,PREPARED_BYTES),'all547Inventory':inventory,
        'originalReceipt':file_identity(tree/'FAILED.json'),'completedEngine':original['engineProducts'],
        'originalSplicer':source_splicer,'originalSupport':file_identity(tree/'normal-support/SUPPORT.json'),
        'currentCompiledRecipes':{'engine':built['recipe'],'engineSDK':envelope['sdkInputs'],
            'splicer':value('splicer/splicer-build.json')['recipe'],
            'splicerSDK':value('splicer/splicer-input.json')['sdkInputs']},
        'relocatedProducts':{k:str(v) for k,v in relocated.items()},
        'reusedRustEvidence':{'cases':list(rust_cases),'executedAt':PREPARED_HEAD},
        'reusedSourceEvidence':{'cases':list(python_cases),'result':original['sourceControls'],'executedAt':PREPARED_HEAD},
        'producerWholePass':False,'receiptReissued':False,'newNativeCasesExecuted':False}
    return tree,relocated,support,proof
