"""Build the exact source-owned async import splicer with upstream commands.

Original source/WIT and the captured compiler namespace stay separate. A built
splicer is an explicitly supplied compiler input, never an API qualification.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
import time

from tools.build_observation import build_environment
from tools.build_process import BuildProcessError, run_bounded_result
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_project import ROOT, digest, fresh, read_file, write_json
from tools.typescript_guest import activation_engine, import_bindgen, promise_library, splicer_input
from tools.typescript_guest.native_build import SOURCES


def compiler_inventory(tools: Path) -> dict:
    from tools.build_observation import file_identity as tool_identity
    rows, total = [], 0
    for name in ('package.json','package-lock.json'):
        if read_file(tools/name) != read_file(ROOT/'sdk/typescript-guest/tools'/name):
            raise ValueError('typescript-source-splicer-original-compiler-lock-differs')
    for path in sorted((tools/'node_modules').rglob('*')):
        if '.bin' in path.relative_to(tools).parts: continue
        if path.is_symlink(): raise ValueError('typescript-source-splicer-compiler-link')
        if path.is_dir(): continue
        size = path.stat().st_size
        if size > 256*1024**2 or total+size > 1024**3 or len(rows) >= 32768:
            raise ValueError('typescript-source-splicer-compiler-closure-limit')
        row = tool_identity(path,'compiler-file') if size else {'digest':digest(read_file(path)),'size':0}
        total += row['size']
        rows.append({'path':path.relative_to(tools).as_posix(),'digest':row['digest'],'size':row['size']})
        if len(rows)>32768 or total>1024**3:
            raise ValueError('typescript-source-splicer-compiler-closure-limit')
    if not rows: raise ValueError('typescript-source-splicer-compiler-closure-required')
    return {'files':rows,'bytes':total}


def transpilation_receipt(output: Path, files: dict[str,bytes]) -> dict:
    """Bind the actual successful command/result to all emitted JS/Wasm bytes."""
    command = json.loads(read_file(output/'transpile.command.json'))
    result = json.loads(read_file(output/'transpile.result.json'))
    if result.get('returncode') != 0:
        raise ValueError('typescript-source-splicer-successful-transpilation-required')
    return {'schemaVersion':'latent.typescript.source-splicer-transpilation.v1',
            'command':command,'result':result,'files':splicer_input.identity(files)}


def derive(source: Path) -> tuple[dict[str,bytes],dict]:
    library = 'crates/spidermonkey-embedding-splicer/src/lib.rs'
    paths = (*import_bindgen.SOURCE_PREIMAGES,library)
    original = {name:read_file(source/name) for name in paths}
    native = {name:read_file(ROOT/'sdk/typescript-guest/activation'/name)
              for name in ('async_import_descriptor.rs','async_import_splice.rs')}
    selected, record = import_bindgen.derive_async_compiler_sources(original,native)
    return selected, record


def build(output: Path, tools: Path, *, node: str = 'node') -> dict:
    if sys.platform != 'linux':
        raise ValueError('typescript-source-splicer-linux-builder-required')
    tools = tools.resolve(strict=True)
    output = output.resolve()
    if (output == ROOT or ROOT in output.parents or output == tools or tools in output.parents
            or output in tools.parents):
        raise ValueError('typescript-source-splicer-independent-fresh-output-required')
    output = fresh(output)
    deadline = time.monotonic()+900
    environment = build_environment(output)
    environment.update(CARGO_HOME=str(output/'cargo-home'),CARGO_TARGET_DIR=str(output/'target'),
        CARGO_BUILD_JOBS='2',CARGO_INCREMENTAL='0',RUSTUP_TOOLCHAIN='1.97.1')
    recipe_paths = ('tools/build_typescript_source_splicer.py','tools/typescript_guest/splicer_build.py',
                    'tools/typescript_guest/import_profile.py','tools/typescript_guest/promise_library.py',
                    'tools/typescript_guest/native_build.py',
                    'tools/typescript_guest/splicer_input.py',*splicer_input.input_paths())
    record = {'schemaVersion':'latent.typescript.source-splicer-build.v1','status':'in-progress',
        'scope':'source-built-compiler-input-only','qualification':'unknown','apiSupport':'not-evaluated',
        'limits':{'overallSeconds':900,'cargoSeconds':600,'transpileSeconds':180,'jobs':2},
        'recipe':{name:file_identity(ROOT/name) for name in recipe_paths}}

    def run(label,*command,seconds=90,cwd=output):
        remaining = min(seconds,deadline-time.monotonic())
        if remaining <= 0: raise ValueError('typescript-source-splicer-deadline')
        write_json(output/(label+'.command.json'),{'command':list(map(str,command)),'maximumSeconds':remaining})
        result = run_bounded_result(list(map(str,command)),cwd,environment,
            timeout_seconds=remaining,max_output_bytes=2*1024**2)
        for name in ('stdout','stderr'):
            (output/(label+'.'+name+'.log')).write_bytes(getattr(result,name))
        write_json(output/(label+'.result.json'),{'returncode':result.returncode,
            'stdout':{'bytes':len(result.stdout),'digest':digest(result.stdout)},
            'stderr':{'bytes':len(result.stderr),'digest':digest(result.stderr)}})
        if result.returncode: raise ValueError('typescript-source-splicer-command-failed:'+label)
        return result.stdout

    stage = 'compiler-tools'
    try:
        package = tools/'node_modules/@bytecodealliance/jco/package.json'
        package_raw = read_file(package)
        metadata = json.loads(package_raw)
        if metadata.get('version') != '1.34.0' or metadata.get('name') != '@bytecodealliance/jco':
            raise ValueError('typescript-source-splicer-pinned-jco-required')
        jco = tools/'node_modules/@bytecodealliance/jco/dist/jco.js'
        namespace = compiler_inventory(tools)
        write_json(output/'compiler-inputs.json',namespace)
        tool_inputs = {name:file_identity(path) for name,path in (
            ('jco-package',package),('jco-entry',jco),('compiler-lock',tools/'package-lock.json'))}
        if run('node-version',node,'--version').strip() != b'v24.19.0':
            raise ValueError('typescript-source-splicer-pinned-node-required')
        if run('rust-version','rustc','--version').split()[:2] != [b'rustc',b'1.97.1']:
            raise ValueError('typescript-source-splicer-pinned-rust-required')
        record['compilerTools'] = tool_inputs
        stage = 'original-source'
        pin = SOURCES['componentize']
        acquired = promise_library.acquire(output/'componentize.archive',pin,deadline)
        source = promise_library.extract(output/'componentize.archive',output/'source',
            'ComponentizeJS-'+activation_engine.COMPONENTIZE_TREE,deadline=deadline)
        selected, derivation = derive(source)
        write_json(output/'source-derivation.json',derivation)
        for name,raw in selected.items(): (source/name).write_bytes(raw)
        cargo_lock = read_file(source/'Cargo.lock')
        original_wit = read_file(source/'crates/spidermonkey-embedding-splicer/wit/spidermonkey-embedding-splicer.wit')
        record['originalCargoLock'] = {'bytes':len(cargo_lock),'digest':digest(cargo_lock)}
        record['originalPublicWit'] = {'bytes':len(original_wit),'digest':digest(original_wit)}
        stage = 'normal-locked-cargo-build'
        run('cargo-build','cargo','build','--locked','--lib','--release','--target','wasm32-wasip1',
            '--package','splicer-component',seconds=600,cwd=source)
        core = output/'target/wasm32-wasip1/release/splicer_component.wasm'
        record['originalCore'] = file_identity(core,64*1024**2)
        stage = 'normal-component-and-transpilation'
        component = output/'spidermonkey-embedding-splicer.wasm'
        run('componentize',node,jco,'new',core,'-o',component,'--wasi-reactor')
        record['component'] = file_identity(component,64*1024**2)
        generated = output/'splicer'
        run('transpile',node,jco,'transpile','-q','--name','spidermonkey-embedding-splicer',component,
            '-o',generated,'--','-O1',seconds=180)
        stage = 'final-integrity'
        if (read_file(source/'Cargo.lock') != cargo_lock or
                read_file(source/'crates/spidermonkey-embedding-splicer/wit/spidermonkey-embedding-splicer.wit') != original_wit
                or any(read_file(source/name)!=raw for name,raw in selected.items())):
            raise ValueError('typescript-source-splicer-original-or-derived-input-changed')
        if record['recipe'] != {name:file_identity(ROOT/name) for name in recipe_paths}:
            raise ValueError('typescript-source-splicer-recipe-changed')
        if tool_inputs != {name:file_identity(path) for name,path in (
                ('jco-package',package),('jco-entry',jco),('compiler-lock',tools/'package-lock.json'))}:
            raise ValueError('typescript-source-splicer-compiler-input-changed')
        if namespace != compiler_inventory(tools):
            raise ValueError('typescript-source-splicer-full-compiler-closure-changed')
        promise_library.recheck_archives(output,{'componentize':pin},{'componentize':acquired})
        from tools.typescript_guest.import_profile import splicer_files
        files = splicer_files(generated)
        write_json(output/'transpile-receipt.json',transpilation_receipt(output,files))
        compilation = {**record,'status':'compiled-and-transpiled','files':splicer_input.identity(files)}
        write_json(output/'splicer-compilation.json',compilation)
        envelope = {'schemaVersion':splicer_input.SCHEMA,'componentizeTree':splicer_input.COMPONENTIZE_TREE,
            'files':splicer_input.identity(files),
            'sdkInputs':[{'path':name,'digest':digest(read_file(ROOT/name)),'size':len(read_file(ROOT/name))}
                         for name in sorted(splicer_input.input_paths())],
            'sourceDerivationDigest':digest(read_file(output/'source-derivation.json')),
            'buildReceiptDigest':digest(read_file(output/'splicer-compilation.json')),
            'transpileReceiptDigest':digest(read_file(output/'transpile-receipt.json')),
            'qualification':'unknown','apiSupport':'not-evaluated','inputTrust':'operator-asserted'}
        splicer_input.validate(envelope,files,{name:read_file(ROOT/name) for name in splicer_input.input_paths()})
        write_json(output/'splicer-input.json',envelope)
        notices = output/'licenses'; notices.mkdir()
        shutil.copyfile(source/'LICENSE',notices/'ComponentizeJS-LICENSE')
        record.update(status='passed',input=file_identity(output/'splicer-input.json'),signedExecution='not-run')
        write_json(output/'splicer-build.json',record)
        return record
    except BaseException as error:
        record.update(status='failed',stage=stage,
            reason=str(error)[:4096] if isinstance(error,(BuildProcessError,ValueError)) else type(error).__name__)
        write_json(output/'FAILED.json',record)
        raise
