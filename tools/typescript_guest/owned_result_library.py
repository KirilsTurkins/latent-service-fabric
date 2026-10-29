"""Hosted reconstruction of ONE pinned completed low-level normal library.

No engine envelope reuse, receipt rewriting, Mach fallback or cache search.
The shared original normal validator is mandatory before any feature build.
"""
import json
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
