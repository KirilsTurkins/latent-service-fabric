"""One fixed failed BUILDER's completed .NET components, never a passed-reader waiver.

No compiler/capture/SDK lookup/native acquisition. Exact old bytes remain old;
only a new normal node programme and current passive CIL classification are new.
"""
from __future__ import annotations
import argparse
from copy import deepcopy
import json
from pathlib import Path
import shutil
import stat
import sys
import time
import zipfile
if __package__ in {None, ''}: sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import guest_api_analysis as api, guest_compatibility as compatibility
from tools import guest_compatibility_context as context
from tools.compatibility_preserved_cells import _name, identity
from tools.dev_workflow.common import digest, encode, require, sha
from tools.phase3_resource_identity import file_identity, inventory as public_inventory
from tools.rust_capsule_project import ROOT, fresh, read_file, read_json, write_json

SOURCE = '61a0be045ca33f44cd2ae1467e272168bccdafb7'
RUN, JOB, ARTIFACT = 40229947914, 121279317428, 12612930511
ARCHIVE = {'bytes': 8875919, 'sha256': 'sha256:6a1c7a07226c571b5a0a4b770f7b7845216c0b39b1f534ba7101566fe81cc46c'}
PIN = {'source':SOURCE,'run':RUN,'job':JOB,'artifact':ARTIFACT,'archive':ARCHIVE}
MEMBERS, EXPANDED = 329, 34604405
MAX_ARCHIVE, MAX_EXPANDED, MAX_FILE, MAX_FILES = 16*1024**2, 64*1024**2, 64*1024**2, 512
CAPTURE = 'sha256:775c748f85de44d2be723780721d716aedf85f96c9881fc334a34a869e4cc3d1'
MAIN = {'baseline': {'digest': 'sha256:f9b5b443355eca0dbd5093795a52d6911eccd210b0e3d49a6242c870b84d165c', 'size': 838},
        'reached': {'digest': 'sha256:1d1d65729dda4e4747a43fe2018fe90878596d5b224250bfceba8048fe88c1ee', 'size': 837}}
WIT = {'wit/world.wit': {'digest':'sha256:0327178f3587f5de0e0317e0b2d4c8d0de9ade245dc7f32dd3ca68e3b6af90da','size':185},
       'wit/deps/clock/package.wit': {'digest':'sha256:a009ecd4ad23d581523fe97b66327ebe352ac27c9c72d4e09ecc9bb003c466ea','size':139}}
ANSWER = [{'ok':'api|answer=42|fresh=1'}]
PINS = {'ADMISSION.json': {'bytes': 46602,
                    'sha256': 'sha256:738e2d0bdab87e18c504983840ce9598f6e0b6dc532e04934c15d8686252cfe9'},
 'FAILED.json': {'bytes': 138059,
                 'sha256': 'sha256:165e27b972d80f4ac931b978d46c6fe9c32978f5c5d5a9333327cb343d52ec1a'},
 'baseline/BUILD-COMPLETE.json': {'bytes': 4430,
                                  'sha256': 'sha256:76ceb8750122aa894ff184d51dbfb4a61f76a4b7d6d4d4d0b6e851b8c85eeae0'},
 'reached/BUILD-COMPLETE.json': {'bytes': 4425,
                                 'sha256': 'sha256:c5d8eb02dfba16c9d3576d604e88ea6ae6eefe5a8dee4868308afab91450ce40'},
 'baseline/source-inputs.json': {'bytes': 24149,
                                 'sha256': 'sha256:1205f7d6c1094620662f58235dbc2aea13dd43789660384c21813504c5e69c59'},
 'reached/source-inputs.json': {'bytes': 24149,
                                'sha256': 'sha256:1facbb7b4cf647f8604cee07cb5144e9e86fae1e08e314b2242a505f221c6136'},
 'baseline/recipe-inputs.json': {'bytes': 8981,
                                 'sha256': 'sha256:cae18db846427000c92cf4792dc05417592b026ef9e6aa29173ac50f3d29c0cb'},
 'reached/recipe-inputs.json': {'bytes': 8981,
                                'sha256': 'sha256:cae18db846427000c92cf4792dc05417592b026ef9e6aa29173ac50f3d29c0cb'}}
CURRENT_API = {'size': 71586, 'digest': 'sha256:ae9f6636d7a03abe43fdc82ce830392453b93705c3852b38e15d453ba978e215'}


def _input(raw):
    return {'digest':digest(raw),'size':len(raw)}


def _archive(path, destination=None):
    require(file_identity(path,MAX_ARCHIVE)==ARCHIVE,'retained-dotnet-exact-failed-archive')
    with zipfile.ZipFile(path) as archive:
        rows=archive.infolist(); names=[row.filename for row in rows]
        require(len(rows)==len(set(names))==MEMBERS<=MAX_FILES
            and sum(row.file_size for row in rows)==EXPANDED<=MAX_EXPANDED,'retained-dotnet-archive-bounds')
        for row in rows:
            _name(row.filename)
            require(not row.is_dir() and stat.S_IFMT(row.external_attr>>16) in (0,stat.S_IFREG)
                and not row.flag_bits&1 and 0<=row.file_size<=MAX_FILE,'retained-dotnet-regular-member')
        admission_raw=archive.read('ADMISSION.json')
        require(identity(admission_raw)==PINS['ADMISSION.json'],'retained-dotnet-admission-pin')
        admission=json.loads(admission_raw)
        require(type(admission) is dict and type(admission.get('files')) is dict
            and set(names)==set(admission['files'])|{'ADMISSION.json'},'retained-dotnet-admitted-union')
        if destination is not None: destination=fresh(destination)
        for row in rows:
            raw=archive.read(row)  # Original CRC checked, exactly bounded public union.
            if row.filename!='ADMISSION.json':
                require(identity(raw)==admission['files'][row.filename],'retained-dotnet-admitted-member')
            if row.filename in PINS: require(identity(raw)==PINS[row.filename],'retained-dotnet-original-pin')
            if destination is not None:
                target=destination/row.filename; target.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
                with target.open('xb') as output: output.write(raw)
                target.chmod(0o600)
    return admission


def _typed_inventory(value, count):
    require(type(value) is dict and len(value)==count,'retained-dotnet-inventory-count')
    for name,row in value.items():
        _name(name)
        require(type(row) is dict and set(row)=={'digest','size'}
            and type(row['size']) is int and 0<=row['size']<=MAX_FILE,'retained-dotnet-inventory-row')
        sha(row['digest'])
    return value


def _inventory_pair(left,right):
    """Pure inventory relation, NOT authentication or reconstructed source bytes."""
    _typed_inventory(left,158);_typed_inventory(right,158)
    require(set(left)==set(right) and left.get('src/Main.cs')==MAIN['baseline']
        and right.get('src/Main.cs')==MAIN['reached']
        and all(left[name]==right[name] for name in left if name!='src/Main.cs'),
        'retained-dotnet-exact-original-Main-only-relation')
    return {'rawSourceWorkspaceReconstructed':False,'nonMainRowsUnchanged':157}


def _original(directory):
    for name,pin in PINS.items():
        require(file_identity(directory/name,MAX_FILE)==pin,'retained-dotnet-original-file-pin')
    failed=read_json(directory/'FAILED.json',1024**2)
    require(failed['status']=='failed' and failed['cell']==failed['language']=='dotnet'
        and failed['sourceCommit']==SOURCE and failed['stage']=='same-original-libraries-one-root-edge'
        and failed['errorCategory']=='DevError' and failed['guestBuildCount']==2
        and failed['nativeBuildCount']==0 and 'reachedSigned' not in failed,
        'retained-dotnet-failed-builder-not-passed')
    require(failed['capturePhase']['acceptedInputIdentity']==CAPTURE
        and failed['capturePhase']['capture']['capturedInputIdentity']==CAPTURE,
        'retained-dotnet-original-accepted-capture')
    source_relation=_inventory_pair(read_json(directory/'baseline/source-inputs.json',1024**2),
        read_json(directory/'reached/source-inputs.json',1024**2))
    source_relation.update(sourceValidation='fixed-authenticated-original-inventories-and-known-Main-preimages',
        sourceBefore=PINS['baseline/source-inputs.json'],sourceAfter=PINS['reached/source-inputs.json'],
        capturedInputIdentity=CAPTURE)
    require(failed['native']['compiledSource']=='17e8e622ecd3307a246196cbb5ca06c0fac37301'
        and (failed['native']['producerRun'],failed['native']['producerJob'])==(40208542534,121214620779),
        'retained-dotnet-original-native-tuple')
    observed=[]
    for build in ('baseline','reached'):
        root=directory/build; complete=read_json(root/'BUILD-COMPLETE.json',65536)
        build_raw=read_file(root/'build-observation.json',1024**2);owner=json.loads(build_raw)
        source_raw=read_file(root/'source-inputs.json',1024**2)
        require(complete['formatVersion']==1 and complete['packageAssembled'] is True
            and complete['observationDigest']==digest(build_raw)
            and complete['sourceDigest']==digest(source_raw)==owner['source']['snapshotDigest']
            and complete['componentDigest']==owner['componentDigest']
            and file_identity(root/'component.wasm',MAX_FILE)==failed[build]['component'],
            'retained-dotnet-completed-original-builder')
        require(owner['componentDigest']==failed[build]['component']['sha256'],
            'retained-dotnet-completed-component')
        materials=api.original_materials(build_raw,{'sourceDigest':digest(source_raw),
            'componentDigest':owner['componentDigest']})
        for name,filename in (('source-snapshot','source-inputs.json'),('build-recipe','recipe-inputs.json'),
                ('package-inputs','package-inputs.json')):
            require(materials[name]['digest']==digest(read_file(root/filename,8*1024**2)),
                'retained-dotnet-original-consumed-material')
        report=compatibility.read(read_file(root/'compatibility-report.json',65536))
        selected=context.read(read_file(root/'compatibility-context.json',65536),report=report)
        _emitted,compiler,_ports,_build,_component=api.inputs(root,report,selected)
        require('compiler-method-reachability' in compiler,'retained-dotnet-original-method-record')
        observed.append(compiler['compiler-method-reachability'])
    require(observed[0]['sourceDigest']==source_relation['sourceBefore']['sha256']
        and observed[1]['sourceDigest']==source_relation['sourceAfter']['sha256'],
        'retained-dotnet-callee-source-association')
    pair=api._dotnet_callee_join(*observed)
    pair={'sourceEvidence':source_relation,'calleeJoin':pair,'builderSourceCommit':SOURCE,
        'scope':'fixed61a-authenticated-completed-builder-reclassification','runtimeExecution':'not-observed'}
    from tools.compatibility_closure_matrix import signed
    signed(failed['baselineSigned'],failed['baseline']['component']['sha256'],2,expected=ANSWER)
    return failed,pair


def _current_sources(original):
    left=read_json(original/'baseline/recipe-inputs.json',1024**2)
    right=read_json(original/'reached/recipe-inputs.json',1024**2)
    _typed_inventory(left,68);_typed_inventory(right,68)
    require(left==right,'retained-dotnet-identical-original-recipes')
    changes={}
    for name,expected in right.items():
        current=_input(read_file(ROOT/_name(name),8*1024**2))
        if name in {'tools/guest_api_analysis.py','tools/guest_compiler_edges.py'}:
            original_pin,current_pin=({ 'size':41055,'digest':'sha256:6477141c8897de13cd73a1179ae9350ed0f01baa2ec4aa85442dfb7c8c45daba'},CURRENT_API) if name=='tools/guest_api_analysis.py' else (
                {'size':18746,'digest':'sha256:4e3d2a2bc6d96fcd4294bc394e25e49e449607d76f512a1de73d2897dad0eb8f'},
                {'size':19180,'digest':'sha256:167de6a71b90f4c2de95440d0578160b3cd5eccce6163ee087c461f0ad436ed8'})
            require(expected==original_pin and current==current_pin,'retained-dotnet-reviewed-passive-postimage')
            changes[name]={'original':expected,'current':current,'scope':'current-passive-diagnostics-only'}
        else: require(current==expected,'retained-dotnet-compiler-recipe-drift')
    require(set(changes)=={'tools/guest_api_analysis.py','tools/guest_compiler_edges.py'},'retained-dotnet-only-reviewed-passive-delta')
    source=read_json(original/'reached/source-inputs.json',1024**2);count=0
    for name,expected in source.items():
        if name.startswith(('vendor/lsf/sdk/','vendor/lsf/wit/')):
            require(_input(read_file(ROOT/_name(name[len('vendor/lsf/'):]),8*1024**2))==expected,
                'retained-dotnet-captured-sdk-wit-drift');count+=1
    require(count==124,'retained-dotnet-exact-captured-sdk-wit-count')
    return {'originalRecipeRows':68,'unchangedRecipeRows':66,'passiveChanges':changes,
        'capturedSDKWITRowsUnchanged':124,'builderSourceCommit':SOURCE,
        'currentCompilerInvocations':0,'currentCaptureInvocations':0,'currentRuntimeSourceRelabelled':False}


def _expected_node_files(original):
    root=original/'reached';rows={}
    entries=list(root.iterdir());require(len(entries)<=128,'retained-dotnet-direct-input-count')
    for path in entries:
        require(not path.is_symlink(),'retained-dotnet-source-link')
        if path.is_file() and (path.suffix=='.json' or path.name=='component.wasm'):
            rows[path.name]={'originalMember':'reached/'+path.name,**file_identity(path,MAX_FILE)}
    for name,pin in WIT.items():
        member='reached/package/layers/'+name
        require(_input(read_file(original/member,65536))==pin,'retained-dotnet-fixed-WIT-source')
        rows[name]={'originalMember':member,'bytes':pin['size'],'sha256':pin['digest']}
    return rows


def verify_package_sources(directory, expected):
    """Recheck actual source bytes; package normalization is NOT source identity."""
    _typed_inventory(expected,8)
    for name,row in expected.items():
        require(_input(read_file(directory/_name(name),MAX_FILE))==row,'retained-dotnet-package-source-changed')
    require(all(expected.get(name)==pin for name,pin in WIT.items()),'retained-dotnet-original-WIT-inventory')


def _node_input(original,destination=None):
    expected=_expected_node_files(original)
    if destination is not None:
        destination=fresh(destination)
        for name,row in expected.items():
            raw=read_file(original/row['originalMember'],MAX_FILE)
            require(identity(raw)=={key:row[key] for key in ('bytes','sha256')},'retained-dotnet-copy-source-changed')
            target=destination/_name(name);target.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
            with target.open('xb') as output:output.write(raw)
    return expected


def _tree(directory):
    observed=public_inventory(directory,maximum_files=MAX_FILES,maximum_bytes=MAX_EXPANDED,
        deadline=time.monotonic()+60)
    return {row['path']:{key:row[key] for key in ('bytes','sha256')} for row in observed['files']}


def _state(output, *, sealed=True):
    children=list(output.iterdir())
    require({path.name for path in children}==({'original.zip','original','node-input','PREPARED.json'}
        if sealed else {'original.zip','original','node-input'}) and not any(path.is_symlink() for path in children),
        'retained-dotnet-preparation-root-union')
    admission=_archive(output/'original.zip')
    expected={**admission['files'],'ADMISSION.json':PINS['ADMISSION.json']}
    require(_tree(output/'original')==expected,'retained-dotnet-original-extraction-changed')
    failed,pair=_original(output/'original')
    equivalence=_current_sources(output/'original')
    nodes=_expected_node_files(output/'original')
    require(_tree(output/'node-input')=={name:{key:row[key] for key in ('bytes','sha256')}
        for name,row in nodes.items()},'retained-dotnet-node-input-union')
    verify_package_sources(output/'node-input',read_json(output/'original/reached/package-inputs.json',1024**2))
    summary={'schemaVersion':'lsf.compatibility.dotnet-retained-builder.v1','origin':{
        'sourceCommit':SOURCE,'run':RUN,'job':JOB,'artifact':ARTIFACT,'archive':ARCHIVE},
        'originalBuilderStatus':'failed','originalFailedIdentity':PINS['FAILED.json'],
        'currentPairIdentity':digest(encode(pair)),'sourceEquivalence':equivalence,
        'nodeInputs':nodes,'originalRuntimeSourceRelabelled':False,
        'sourceWorkspaceReconstructed':False,'currentCompilerInvocations':0,'currentCaptureInvocations':0}
    return {'summary':summary,'originalFailed':failed,'currentPair':pair,'sourceEquivalence':equivalence,
        'nodeInput':output/'node-input','original':output/'original'}


def prepare(output,*,archive):
    """Local exact archive ONLY. Owning workflow supplies already-authenticated origin."""
    output=Path(output).absolute();archive=Path(archive)
    require(not archive.is_symlink(),'retained-dotnet-no-archive-link')
    archive=archive.resolve(strict=True)
    require(not archive.is_symlink() and output!=archive and output not in archive.parents,
        'retained-dotnet-separated-preparation')
    _archive(archive)  # Full fixed hash/CRC/admission BEFORE materialization.
    output=fresh(output)
    shutil.copyfile(archive,output/'original.zip')
    _archive(output/'original.zip',output/'original')
    _node_input(output/'original',output/'node-input')
    state=_state(output,sealed=False)
    write_json(output/'PREPARED.json',state['summary'])
    return state


def verify_prepared(output):
    output=Path(output).resolve(strict=True)
    state=_state(output)
    require(read_json(output/'PREPARED.json',1024**2)==state['summary'],
        'retained-dotnet-rehashed-preparation')
    return state


def run(prepared,native,output,deadline,source_commit):
    """Only the existing normal node owner; no compiler, new deadline or process owner."""
    import math
    from tools import compatibility_closure_node as node
    require(type(deadline) in (int,float) and math.isfinite(deadline)
        and deadline>time.monotonic() and type(source_commit) is str and len(source_commit)==40
        and all(c in '0123456789abcdef' for c in source_commit),'retained-dotnet-actual-node-bound')
    state=verify_prepared(prepared);original=state['originalFailed']
    # The qualifier independently applies unchanged native reader/current_source
    # gates before and after; this leaf also binds the three executable bytes it uses.
    products=original['native']['products']
    for key in ('latent','latentd','capsule_authoring'):
        name='examples/'+key if key=='capsule_authoring' else key
        require(file_identity(native[key],256*1024**2)==products[name],'retained-dotnet-fixed-native-product')
    output=Path(output).absolute();prepared=Path(prepared).resolve(strict=True)
    require(output!=prepared and output not in prepared.parents and prepared not in output.parents,
        'retained-dotnet-separated-current-run')
    output=fresh(output)
    result={'schemaVersion':'lsf.compatibility.dotnet-retained-node.v1','status':'incomplete',
        'cell':'dotnet','language':'dotnet','sourceCommit':source_commit,
        'builderSourceCommit':SOURCE,'baselineRuntimeSourceCommit':SOURCE,'nodeSourceCommit':source_commit,
        'currentDiagnosticSourceCommit':source_commit,'originalBuilderStatus':'failed',
        'originalOrigin':state['summary']['origin'],'originalFailed':original,
        'capturePhase':deepcopy(original['capturePhase']),'baseline':deepcopy(original['baseline']),
        'reached':deepcopy(original['reached']),'baselineSigned':deepcopy(original['baselineSigned']),
        'compilerPair':deepcopy(state['currentPair']['calleeJoin']),
        'currentCompilerPair':state['currentPair'],'sourceEquivalence':state['sourceEquivalence'],
        'currentCompilerInvocations':0,'currentCaptureInvocations':0,'currentNativeBuilds':0,
        'originalBuildCount':2,'currentSignedInvocations':None,'arbitraryApiSafety':'unknown',
        'initializationDisposition':'unknown','authority':'none','wholeTicketComplete':False}
    try:
        result['reachedSigned']=node.execute(state['nodeInput'],native,output/'reached-node',
            deadline,'dotnet',kind='api-pair',expected=ANSWER)
        from tools.compatibility_closure_matrix import signed
        signed(result['reachedSigned'],original['reached']['component']['sha256'],2,expected=ANSWER)
        verify_prepared(prepared)
        for key in ('latent','latentd','capsule_authoring'):
            name='examples/'+key if key=='capsule_authoring' else key
            require(file_identity(native[key],256*1024**2)==products[name],'retained-dotnet-native-product-changed')
        result.update(status='pending-final-owner-checks',currentSignedInvocations=2)
        require(len(encode(result))<=1024**2,'retained-dotnet-result-bound')
        write_json(output/'NODE-COMPLETED.json',result) # Qualifier owns final native/source check and qualified.json.
        return result
    except BaseException as fault:
        result.update(status='failed',errorCategory=type(fault).__name__)
        try:
            if len(encode(result))<=1024**2:write_json(output/'FAILED.json',result)
        except (ValueError,OSError): pass  # Never replace the original failure.

        raise


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    entry=sub.add_parser('prepare');entry.add_argument('--archive',type=Path,required=True);entry.add_argument('--output',type=Path,required=True)
    entry=sub.add_parser('verify');entry.add_argument('--prepared',type=Path,required=True)
    args=parser.parse_args(argv)
    state=prepare(args.output,archive=args.archive) if args.command=='prepare' else verify_prepared(args.prepared)
    print(json.dumps(state['summary'],sort_keys=True,separators=(',',':')))
    return 0

if __name__=='__main__':raise SystemExit(main())
