"""Closed canonical diagnostic construction using normally validated OWN inputs.

This module neither acquires inputs nor runs a build when imported. A completed
authenticated owning artifact is a prerequisite; it grants no release support.
"""
from __future__ import annotations
import json
from pathlib import Path
import re

from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_project import ROOT,read_file,write_json,digest
from tools.typescript_guest import activation_engine,native_build,runtime_profile
from tools.typescript_guest import owned_result_controls as controls,owned_result_fixture
from tools.typescript_guest.compiler import Compiler
from tools.typescript_guest.probe import semantic

ENGINE_FILES=('engine.wasm','engine-input.json','engine-build.json','engine-compilation.json','source-derivation.json')


def require(value,reason):
    if not value:raise ValueError(reason)


def select_products(prepared:Path,expected_owner_head:str)->dict:
    """Recheck actual prerequisite evidence AND the original normal validators.

    The caller must first authenticate the fixed GitHub run/artifact. This
    function supplies no publisher trust and never edits/reissues an envelope.
    """
    require(re.fullmatch(r'[0-9a-f]{40}',expected_owner_head) is not None,'owned-component-owner-head')
    prepared=prepared.resolve(strict=True)
    raw=read_file(prepared/'OWN-RESULTS.json',8*1024**2);receipt=json.loads(raw)
    require(type(receipt) is dict,'owned-component-prerequisite-receipt-shape')
    require(receipt.get('schemaVersion')=='latent.typescript.owned-result-prerequisites.v1'
            and receipt.get('scope')=='fresh-normal-compiler-engine-unit-native-ABI-prerequisites'
            and receipt.get('status')=='passed' and receipt.get('sourceCommit')==expected_owner_head
            and all(type(receipt.get(name)) is int for name in
                ('freshSplicerBuildCount','freshEngineBuildCount','machBuildCount'))
            and receipt.get('freshSplicerBuildCount')==receipt.get('freshEngineBuildCount')==1
            and receipt.get('machBuildCount')==0,'owned-component-completed-fresh-prerequisites')
    origin=receipt.get('workflowOrigin',{})
    require(origin.get('GITHUB_REPOSITORY')=='KirilsTurkins/latent-service-fabric'
            and origin.get('GITHUB_SHA')==origin.get('GITHUB_WORKFLOW_SHA')==expected_owner_head
            and origin.get('GITHUB_EVENT_NAME') in ('push','workflow_dispatch')
            and origin.get('GITHUB_WORKFLOW_REF')=='KirilsTurkins/latent-service-fabric/.github/workflows/typescript-owned-results.yml@'+origin.get('GITHUB_REF',''),
            'owned-component-owning-workflow-origin')
    for name in ('canonicalOwnComponentExecuted','tableReuseQualified','signedExecution',
                 'physicalProviderQualified','wholeCostQualification'):
        require(receipt.get(name) is False,'owned-component-prerequisites-are-not-canonical-qualification')
    controls.source_controls(receipt['sourceControls'])
    rust=read_file(prepared/'actual-rust-units.stdout.log',1024**2)
    require(controls.rust_cases(rust)==receipt['actualRustCases'],'owned-component-actual-rust-evidence')
    commands=receipt.get('commands',[])
    units=[row for row in commands if row.get('label')=='actual-rust-units']
    require(len(units)==1 and units[0].get('returncode')==0
            and units[0].get('stdout')=={'bytes':len(rust),'sha256':digest(rust)},
            'owned-component-original-rust-log-identity')
    for field,cases,validate in [('nativeRows',controls.NATIVE_CASES,controls.native_case),
                                  ('lifecycleRows',controls.LIFECYCLE_CASES,controls.lifecycle_case)]:
        rows=receipt.get(field,[])
        require(type(rows) is list and [row.get('case') for row in rows]==list(cases),
                'owned-component-all-native-prerequisites-required')
        for row,case in zip(rows,cases,strict=True):
            validate(row,case)
            require(json.loads(read_file(prepared/(case+'.stdout.log'),1024**2))==row,
                    'owned-component-original-native-row')
    require(receipt.get('engineProducts')=={name:file_identity(prepared/'engine'/name,64*1024**2)
                for name in ENGINE_FILES},'owned-component-original-engine-products')
    require(native_build.source_splicer(prepared/'splicer')==receipt['splicer'],
            'owned-component-original-normal-splicer-validator')
    engine_raw=read_file(prepared/'engine/engine.wasm',64*1024**2)
    envelope=read_file(prepared/'engine/engine-input.json',65536)
    sdk={name:read_file(ROOT/name) for name in activation_engine.engine_input_paths(runtime_profile.IMPORT_PROFILE)}
    engine=runtime_profile.validate_engine(json.loads(envelope),engine_raw,sdk,
        read_file(ROOT/'wit/platform/activation-runtime/package.wit'),profile=runtime_profile.IMPORT_PROFILE)
    require(engine['compilerSplicerInputDigest']==digest(read_file(prepared/'splicer/splicer-input.json')),
            'owned-component-original-engine-splicer-pair')
    return {'owningReceipt':{'bytes':len(raw),'sha256':digest(raw)},'sourceCommit':expected_owner_head,
            'engine':receipt['engineProducts'],'splicer':receipt['splicer'],
            'classification':'normal-input-and-native-prerequisites-only'}


def compile_fixture(prepared:Path,expected_owner_head:str,tools:Path,output:Path,commands)->tuple[Path,dict]:
    """Only called by a later reviewed bounded host programme, never locally."""
    selected=select_products(prepared,expected_owner_head)
    # The original Commands root must be this fresh compiler workspace so the
    # unchanged normal isolation adapter can use its actual allowed cwd.
    output=output.resolve(strict=True)
    require(output==commands.root.resolve(strict=True)
            and all(path.name=='logs' and path.is_dir() for path in output.iterdir()),
            'owned-component-fresh-normal-commands-workspace')
    expected={name:read_file(ROOT/'sdk/typescript-guest/tools'/name) for name in ('package.json','package-lock.json')}
    compiler=Compiler(tools,commands,expected,isolated_workspace=output,
        runtime_profile=runtime_profile.IMPORT_PROFILE,
        engine=prepared/'engine/engine.wasm',engine_receipt=prepared/'engine/engine-input.json',
        splicer=prepared/'splicer/splicer',splicer_receipt=prepared/'splicer/splicer-input.json')
    fixture=output/'fixture';fixture_record=owned_result_fixture.prepare(fixture)
    compiler.isolation.protect_inputs(fixture)
    compiled=output/'compiled';compiled.mkdir()
    selection=compiled/'selection.json'
    write_json(selection,{'profile':runtime_profile.IMPORT_PROFILE,'engineInput':compiler.engine_metadata,
                         'compilerSplicerInput':compiler.source_splicer_metadata})
    graph=semantic(json.loads(compiler.run('own-fixture-types',compiler.wasm,'component','wit',fixture,'--json')))
    compiler.run('own-fixture-componentize',compiler.node,fixture/'recipe/componentize.mjs',compiler.compiler,
        fixture,fixture/'application.js',compiled,owned_result_fixture.WORLD,compiler.engine,selection,
        compiler.source_splicer/'spidermonkey-embedding-splicer.js',compiler.tools/'node_modules/acorn/dist/acorn.mjs')
    bare,embedded,component=[compiled/name for name in ('bare.wasm','embedded.wasm','component.wasm')]
    compiler.run('own-fixture-strip',compiler.wasm,'strip','--delete','^component-type',compiled/'core.wasm','-o',bare)
    compiler.run('own-fixture-embed',compiler.wasm,'component','embed',fixture,bare,'--world',owned_result_fixture.WORLD,'-o',embedded)
    compiler.run('own-fixture-compose',compiler.wasm,'component','new',embedded,'-o',component)
    compiler.run('own-fixture-validate',compiler.wasm,'validate','--features','all',component)
    final=semantic(json.loads(compiler.run('own-fixture-final-types',compiler.wasm,'component','wit',component,'--json')))
    require(runtime_profile.compiled_world_matches(graph,final,owned_result_fixture.WORLD,
        profile=runtime_profile.IMPORT_PROFILE,engine_input=compiler.engine_metadata,
        source_splicer_digest=digest(read_file(prepared/'splicer/splicer-input.json'))),
        'owned-component-authoritative-contract-changed')
    compiler.check_unchanged()
    require(selected==select_products(prepared,expected_owner_head),'owned-component-input-changed')
    require(fixture_record['fixtureRecipe']=={name:file_identity(fixture/'recipe'/name)
                for name in fixture_record['fixtureRecipe']},'owned-component-fixture-recipe-changed')
    require(fixture_record['world']==file_identity(fixture/'world.wit')
            and fixture_record['application']==file_identity(fixture/'application.js'),
            'owned-component-fixture-source-changed')
    return component,{'scope':'canonical-diagnostic-build-only','component':file_identity(component,64*1024**2),
                      'selectedPrerequisites':selected,'fixture':fixture_record,
                      'runtimeMaterials':compiler.runtime_materials(),'executed':False}
