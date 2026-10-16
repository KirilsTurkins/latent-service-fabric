"""Normal upstream CMake build of the source-owned Promise/clock engine.

This consumes the successful normal-mach library from the preceding bounded
builder. An emitted engine is a compiler input; runtime qualification is separate.
"""
from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
import time

from tools.build_observation import build_environment
from tools.build_process import BuildProcessError, run_bounded_result
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_project import ROOT, digest, fresh, read_file, write_json
from tools.typescript_guest import activation_engine as activation, clock_engine as clock
from tools.typescript_guest import promise_library, runtime_profile as runtime

SOURCES = {
    'componentize': {'url': 'https://codeload.github.com/bytecodealliance/ComponentizeJS/tar.gz/'+activation.COMPONENTIZE_TREE,
        'bytes': 165706, 'sha256': '2a6ce6a343cb8547a41ed1d0c96ce916be3d754ba8d993bc755334f234e2cdc5'},
    'starling': {'url': 'https://codeload.github.com/bytecodealliance/StarlingMonkey/tar.gz/'+activation.STARLING_COMMIT,
        'bytes': 870167, 'sha256': 'ce27045db832476faaf752940c9c302d8df1241a6e17ca1eca47fd3054998949'},
}


def sources(directory: Path) -> tuple[dict[str, bytes], list[dict]]:
    result, links = {}, []
    total = 0
    for path in sorted(directory.rglob('*')):
        if path.is_symlink():
            target = path.resolve(strict=True)
            if not target.is_relative_to(directory) or not target.is_file():
                raise ValueError('typescript-native-source-link-escaped')
            links.append({'path':path.relative_to(directory).as_posix(),
                          'target':path.readlink().as_posix(), **file_identity(target)})
        elif path.is_file():
            raw = read_file(path); total += len(raw)
            if len(result) >= 4096 or total > 32*1024**2:
                raise ValueError('typescript-native-source-carrier-limit')
            result[path.relative_to(directory).as_posix()] = raw
        elif not path.is_dir():
            raise ValueError('typescript-native-special-source-file')
    return result, links


def selected_sources(original: dict, jobs: dict, clocks: dict) -> tuple[dict, dict]:
    native = lambda names: {name:read_file(ROOT/'sdk/typescript-guest/activation'/name) for name in names}
    selected, queue = activation.derive_queue_experiment(original, native(activation.NATIVE_SOURCES), jobs)
    selected, timing = clock.extend_selected_engine_source(selected, native(clock.CLOCK_NATIVE_SOURCES),
        read_file(ROOT/'wit/platform/clock/package.wit'), clocks)
    cmake = selected['CMakeLists.txt']
    extra = ('\ntarget_sources(starling-raw.wasm PRIVATE\n'
        '  "${CMAKE_CURRENT_SOURCE_DIR}/lsf/native_clock_engine.cpp"\n'
        '  "${CMAKE_CURRENT_SOURCE_DIR}/lsf/clocks.c"\n'
        '  "${CMAKE_CURRENT_SOURCE_DIR}/lsf/clocks_component_type.o")\n'
        'target_include_directories(extension_api INTERFACE "${CMAKE_CURRENT_SOURCE_DIR}/lsf")\n')
    selected['CMakeLists.txt'] = cmake+extra.encode()
    rust_build = 'StarlingMonkey/cmake/build-crates.cmake'
    selected[rust_build] = activation.replace_once(selected[rust_build],b'        NO_LINKER_OVERRIDE\n)',
        b'        NO_LINKER_OVERRIDE\n        LOCKED\n)','normal-cmake-locked-cargo-closure')
    return selected, {'queue':queue, 'clocks':timing,
        'integrationSources':{name:file_bytes(selected[name]) for name in ('CMakeLists.txt',rust_build)},
        'qualification':'unknown'}


def file_bytes(raw: bytes) -> dict:
    return {'bytes':len(raw), 'sha256':digest(raw)}


def supporting_objects(cmake: bytes) -> list[str]:
    matches = re.findall(rb'(?s)    set\(SM_OBJ_FILES\n(.*?)\n    \)', cmake)
    if len(matches) != 1:
        raise ValueError('typescript-native-upstream-supporting-objects-shape')
    names = matches[0].decode().split()
    if (not 1 <= len(names) <= 64 or len(set(names)) != len(names)
            or any(re.fullmatch(r'[A-Za-z0-9_/-]+\.o', name) is None
                   or '..' in PurePosixPath(name).parts or PurePosixPath(name).is_absolute()
                   or PurePosixPath(name).as_posix() != name for name in names)):
        raise ValueError('typescript-native-upstream-supporting-objects-path')
    return names


def materialize_headers(library_root: Path, target: Path, deadline: float) -> dict:
    source = library_root/'obj/dist/include'
    target.mkdir()
    total, count, identities = 0, 0, {}
    for path in sorted(source.rglob('*')):
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(library_root):
            raise ValueError('typescript-native-header-target-escaped')
        destination = target/path.relative_to(source)
        if path.is_dir():
            if path.is_symlink():
                raise ValueError('typescript-native-directory-header-link-unsupported')
            destination.mkdir(exist_ok=True)
        elif resolved.is_file():
            raw = read_file(resolved); total += len(raw); count += 1
            if count > 8192 or total > 128*1024**2 or time.monotonic() >= deadline:
                raise ValueError('typescript-native-installed-header-bound')
            destination.write_bytes(raw)
            identities[destination.relative_to(target).as_posix()] = file_bytes(raw)
        else:
            raise ValueError('typescript-native-special-header')
    confdefs = read_file(library_root/'obj/js/src/js-confdefs.h')
    installed = target/'js-confdefs.h'
    if installed.exists() and read_file(installed) != confdefs:
        raise ValueError('typescript-native-normal-confdefs-differs')
    installed.write_bytes(confdefs)
    identities['js-confdefs.h'] = file_bytes(confdefs)
    return identities


def build(output: Path, library_root: Path, *, bindgen: str = 'wit-bindgen', wasm_tools: str = 'wasm-tools') -> dict:
    if sys.platform != 'linux':
        raise ValueError('typescript-native-linux-builder-required')
    library_root = library_root.resolve(strict=True)
    output = output.resolve()
    if output == ROOT or ROOT in output.parents or output == library_root or library_root in output.parents:
        raise ValueError('typescript-native-fresh-independent-output-required')
    output = fresh(output)
    deadline = time.monotonic()+1200
    environment = build_environment(output)
    record = {'schemaVersion':'latent.typescript.native-engine-source-build.v1', 'status':'in-progress',
        'scope':'normal-cmake-engine-compile-only', 'qualification':'unknown', 'apiSupport':'not-evaluated',
        'limits':{'overallSeconds':1200, 'configureSeconds':600, 'buildSeconds':900, 'jobs':2},
        'sources':SOURCES}
    recipe_paths = ('tools/build_typescript_native_engine.py','tools/typescript_guest/native_build.py',
                    *activation.engine_input_paths(runtime.CLOCK_PROFILE))
    record['recipe'] = {name:file_identity(ROOT/name) for name in recipe_paths}

    def run(label, *command, seconds=90, cwd=output):
        remaining = min(seconds, deadline-time.monotonic())
        if remaining <= 0:
            raise ValueError('typescript-native-build-deadline')
        write_json(output/(label+'.command.json'), {'command':list(map(str,command)), 'maximumSeconds':remaining})
        result = run_bounded_result(list(map(str,command)), cwd, environment,
            timeout_seconds=remaining, max_output_bytes=4*1024**2)
        for name in ('stdout','stderr'):
            (output/(label+'.'+name+'.log')).write_bytes(getattr(result,name))
        if result.returncode:
            raise ValueError('typescript-native-command-failed:'+label)
        return result.stdout

    stage = 'library-input'
    try:
        raw_receipt = read_file(library_root/'library-build.json')
        library = json.loads(raw_receipt)
        if (library.get('schemaVersion') != 'latent.typescript.promise-library-source-build.v1'
                or library.get('status') != 'passed' or library.get('scope') != 'intrinsic-hook-library-compile-only'
                or library.get('qualification') != 'unknown' or library.get('sources') != promise_library.SOURCES
                or library.get('library',{}).get('path') != 'obj/js/src/build/libjs_static.a'):
            raise ValueError('typescript-native-successful-original-library-receipt-required')
        before = file_identity(library_root/library['library']['path'],512*1024**2)
        if before != {key:library['library'][key] for key in ('bytes','sha256')}:
            raise ValueError('typescript-native-library-byte-identity')
        expected_recipe = {'tools/build_typescript_promise_library.py','tools/typescript_guest/promise_library.py',
            'tools/typescript_guest/promise_engine.py','tools/typescript_guest/activation_engine.py',
            'sdk/typescript-guest/activation/promise_hooks.h'}
        if set(library['recipe']) != expected_recipe:
            raise ValueError('typescript-native-library-recipe-inventory')
        for name, identity in library['recipe'].items():
            if file_identity(ROOT/name) != identity:
                raise ValueError('typescript-native-library-recipe-drift')
        header = ROOT/'sdk/typescript-guest/activation/promise_hooks.h'
        exported = library_root/'obj/dist/include/js/ActivationPromiseHooks.h'
        if promise_library.installed_header_identity(library_root,exported,read_file(header)) != library['exportedHeader']:
            raise ValueError('typescript-native-original-header-identity')
        promise_library.recheck_archives(library_root,promise_library.SOURCES,
            {name:json.loads(read_file(library_root/(name+'-acquisition.json'))) for name in promise_library.SOURCES})
        record['libraryInput'] = file_identity(library_root/'library-build.json')
        record['libraryProduct'] = before
        stage = 'source-acquisition'
        identities = {name:promise_library.acquire(output/(name+'.archive'),value,deadline)
                      for name,value in SOURCES.items()}
        source = promise_library.extract(output/'componentize.archive',output/'componentize-source',
            'ComponentizeJS-'+activation.COMPONENTIZE_TREE,deadline=deadline)
        starling = promise_library.extract(output/'starling.archive',output/'starling-source',
            'StarlingMonkey-'+activation.STARLING_COMMIT,deadline=deadline)
        shutil.copytree(starling,source/'StarlingMonkey',dirs_exist_ok=True,symlinks=True)
        original, links = sources(source)
        stage = 'actual-bindings'
        if run('bindgen-version',bindgen,'--version').strip() != b'wit-bindgen-cli 0.62.0':
            raise ValueError('typescript-native-pinned-bindgen-required')
        if run('wasm-tools-version',wasm_tools,'--version').split()[:2] != [b'wasm-tools',b'1.254.0']:
            raise ValueError('typescript-native-pinned-wasm-tools-required')

        def generated(label, package, imports, dependencies):
            wit = output/(label+'-wit'); wit.mkdir(); (wit/'deps').mkdir()
            for name in dependencies:
                shutil.copytree(ROOT/'wit/platform'/name,wit/'deps'/name)
            (wit/'world.wit').write_text('package '+package+';\nworld '+label+' {\n'+
                ''.join('  import '+name+';\n' for name in imports)+'}\n',encoding='utf-8')
            generated = output/(label+'-generated')
            run(label+'-bindings',bindgen,'c',wit,'--world',label,'--out-dir',generated)
            return {path.name:read_file(path) for path in generated.iterdir() if path.is_file()}

        jobs = generated('jobs','latent:typescript-activation@0.1.0',[runtime.ACTIVATION_INTERFACE],['activation-runtime'])
        clocks = generated('clocks','latent:typescript-clock@0.1.0',list(clock.CLOCK_INTERFACES),['clock'])
        selected, derivation = selected_sources(original,jobs,clocks)
        derivation['upstreamContainedLinks'] = links
        write_json(output/'source-derivation.json',derivation)
        for name, raw in selected.items():
            path = source/name; path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(raw)
        stage = 'original-library-combination'
        combined = output/'spidermonkey'; combined.mkdir()
        record['installedHeaders'] = materialize_headers(library_root,combined/'include',deadline)
        objects = supporting_objects(original['StarlingMonkey/cmake/spidermonkey.cmake'])
        object_paths = [library_root/'obj'/name for name in objects]
        record['supportingObjects'] = {name:file_identity(path) for name,path in zip(objects,object_paths)}
        archive = combined/'libspidermonkey.a'
        shutil.copyfile(library_root/library['library']['path'],archive)
        wasi = library_root/'wasi-source/wasi-sdk-30.0-x86_64-linux'
        run('combine-normal-library',wasi/'bin/llvm-ar','-q',archive,*object_paths)
        record['combinedLibrary'] = file_identity(archive,512*1024**2)
        environment.update(SPIDERMONKEY_BINARIES=str(combined),CPM_SOURCE_CACHE=str(output/'cpm-cache'),
            CARGO_BUILD_JOBS='2',RUSTUP_TOOLCHAIN='1.97.1')
        environment['PATH'] = str(library_root)+':'+environment['PATH']
        stage = 'normal-cmake-build'
        cmake = output/'build'
        run('cmake-configure','cmake','-S',source,'-B',cmake,'-DCMAKE_BUILD_TYPE=Release',
            '-DCPM_wasi-sdk_SOURCE='+str(wasi),'-DENABLE_JS_DEBUGGER=OFF','-DWEVAL=OFF',seconds=600)
        run('cmake-build','cmake','--build',cmake,'--target','starlingmonkey_embedding','--parallel','2',seconds=900)
        stage = 'product-integrity'
        core = read_file(source/'lib/starlingmonkey_embedding.wasm',64*1024**2)
        if core[:8] != b'\0asm\x01\0\0\0':
            raise ValueError('typescript-native-real-core-product-required')
        run('validate-core',wasm_tools,'validate',source/'lib/starlingmonkey_embedding.wasm')
        if before != file_identity(library_root/library['library']['path'],512*1024**2):
            raise ValueError('typescript-native-original-library-changed')
        if record['supportingObjects'] != {name:file_identity(path) for name,path in zip(objects,object_paths)}:
            raise ValueError('typescript-native-original-supporting-object-changed')
        if record['installedHeaders'] != {name:file_identity(combined/'include'/name)
                                        for name in record['installedHeaders']}:
            raise ValueError('typescript-native-staged-header-changed')
        if promise_library.installed_header_identity(library_root,exported,read_file(header)) != library['exportedHeader']:
            raise ValueError('typescript-native-original-header-changed')
        promise_library.recheck_archives(output,SOURCES,identities)
        if any(read_file(source/name) != raw for name,raw in selected.items()):
            raise ValueError('typescript-native-selected-source-changed')
        if record['recipe'] != {name:file_identity(ROOT/name) for name in recipe_paths}:
            raise ValueError('typescript-native-recipe-or-sdk-source-changed')
        if read_file(library_root/'library-build.json') != raw_receipt:
            raise ValueError('typescript-native-original-library-receipt-changed')
        product = output/'engine.wasm'; product.write_bytes(core)
        notices = output/'licenses'; notices.mkdir()
        for label, path in (('ComponentizeJS-LICENSE',source/'LICENSE'),('StarlingMonkey-LICENSE',starling/'LICENSE'),
                            ('Firefox-LICENSE',library_root/'licenses/Firefox-LICENSE.txt')):
            (notices/label).write_bytes(read_file(path))
        record.update(status='core-compiled',engine=file_identity(product,64*1024**2),signedExecution='not-run')
        write_json(output/'engine-compilation.json',record)
        sdk = {name:read_file(ROOT/name) for name in activation.engine_input_paths(runtime.CLOCK_PROFILE)}
        envelope = {'schemaVersion':runtime.ENGINE_SCHEMA, 'profile':runtime.CLOCK_PROFILE,
            'coreDigest':digest(core),'coreBytes':len(core),
            'sdkInputs':[{'path':name,'digest':digest(raw),'size':len(raw)} for name,raw in sorted(sdk.items())],
            'runtimeWitDigest':digest(read_file(ROOT/'wit/platform/activation-runtime/package.wit')),
            'upstream':runtime.SOURCE_PINS,'sourceDerivationDigest':digest(read_file(output/'source-derivation.json')),
            'buildReceiptDigest':digest(read_file(output/'engine-compilation.json')),
            'qualification':'unknown','apiSupport':'not-evaluated','inputTrust':'operator-asserted'}
        runtime.validate_engine(envelope,core,sdk,read_file(ROOT/'wit/platform/activation-runtime/package.wit'),profile=runtime.CLOCK_PROFILE)
        write_json(output/'engine-input.json',envelope)
        record.update(status='passed',input=file_identity(output/'engine-input.json'))
        write_json(output/'engine-build.json',record)
        return record
    except BaseException as error:
        record.update(status='failed',stage=stage,
            reason=str(error)[:4096] if isinstance(error,(BuildProcessError,ValueError)) else type(error).__name__)
        write_json(output/'FAILED.json',record)
        raise
