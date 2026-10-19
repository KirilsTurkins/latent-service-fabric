"""Explicit Rust entropy diagnostic using two separately authenticated compiled sources."""
import argparse
import hashlib
from pathlib import Path, PurePosixPath
import stat
import sys
import zipfile

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import rust_entropy_replay_acquisition as acquisition
from tools import qualify_rust_standard_entropy as qualification
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_project import ROOT, digest, fresh, read_file, read_json, write_json

ORIGINAL = '6ffab636e647f93bfa12fda12a0383316f8dce8d'
SOURCE_SHA = 'sha256:1acedf7ad8b3516a495fdabb68c2782da548d4987fbad448a0d23d5a0517cc03'
QUALIFICATION_SHA = 'sha256:a6005a5b11e92ea2bad0885774d72a96704e578355804c6fdeba5f987e9a7ecf'
NATIVE_IDENTITY = {'sha256': 'sha256:3df270a85649e9b9d9cd6900195eae101ff84ef5123239a960796010e0d6819f',
    'files': 3168, 'bytes': 23907276, 'scope': acquisition.HOST_IDENTITY['scope'],
    'hermetic': False, 'implicitCompilerInputs': 'not-attested'}


def verify(prepared):
    raw = read_file(prepared/'qualification.json', 1024**2)
    source = read_file(prepared/'source-inputs.json', 1024**2)
    frozen = read_file(ROOT/'tools/diagnostics/rust-entropy-original-source6ffab.json', 1024**2)
    require(digest(raw) == QUALIFICATION_SHA and digest(source) == SOURCE_SHA
            and source == frozen == read_file(prepared/'source-inputs-after.json', 1024**2),
            'rust-entropy-replay-fixed-original-receipts')
    old = read_json(prepared/'qualification.json')
    require(old['status'] == old['node']['status'] == 'passed'
            and old['sourceIdentityDigest'] == SOURCE_SHA
            and acquisition.git_source_identity(ORIGINAL) == NATIVE_IDENTITY
            and read_json(prepared/'source-inputs.json')['runtime'] == NATIVE_IDENTITY,
            'rust-entropy-replay-frozen-original-source')
    require(set(old['binaries']) == set(qualification.PRODUCTS), 'rust-entropy-replay-original-five')
    products = {}
    for name in qualification.PRODUCTS:
        binary = prepared/'native-binaries'/name.replace('/', '-')
        # Original Rust receipt uses the shared build observer digest/size shape.
        expected = old['binaries'][name]
        actual = file_identity(binary, 512*1024**2)
        require(actual == expected, 'rust-entropy-replay-original-product')
        products[name] = binary
    qualification.companions(prepared, old)
    acquisition.validate_host(prepared/'host')
    return old, products


def prepare(output):
    output = fresh(output)
    artifact = acquisition.Artifact('rust')
    archive = output/'original-public-products.zip'
    artifact.remote.seek(0)
    checksum = hashlib.sha256()
    remaining = acquisition.SPECS['rust'][1]
    with archive.open('xb') as target:
        while remaining:
            raw = artifact.remote.read(min(1024**2, remaining))
            require(bool(raw), 'rust-entropy-replay-short-archive')
            checksum.update(raw);target.write(raw);remaining -= len(raw)
    require('sha256:'+checksum.hexdigest() == acquisition.SPECS['rust'][2], 'rust-entropy-replay-archive-digest')
    with zipfile.ZipFile(archive) as data:
        rows = data.infolist()
        require(len(rows) == 54 and len({row.filename for row in rows}) == 54
                and sum(row.file_size for row in rows) == 310890033, 'rust-entropy-replay-exact-public-archive')
        for row in rows:
            path = PurePosixPath(row.filename)
            require(str(path) == row.filename and not path.is_absolute() and '..' not in path.parts
                    and '\\' not in row.filename and ':' not in row.filename
                    and not row.is_dir() and 0 < row.file_size <= 512*1024**2
                    and stat.S_IFMT(row.external_attr >> 16) in (0, stat.S_IFREG), 'rust-entropy-replay-member-bound')
            destination = output/path
            require(not destination.exists(), 'rust-entropy-replay-existing-member')
            destination.parent.mkdir(parents=True, exist_ok=True)
            with data.open(row) as source, destination.open('xb') as target:
                count = 0
                while raw := source.read(1024**2):
                    count += len(raw); require(count <= row.file_size, 'rust-entropy-replay-expanded-bound');target.write(raw)
            require(count == row.file_size, 'rust-entropy-replay-expanded-length')
            destination.chmod(0o600)
    host = acquisition.retrieve_host(output/'host')
    old, products = verify(output)
    value = {'schemaVersion':'latent.rust.entropy-replay-materials.v1', 'originalCompiledSource': ORIGINAL,
        'originalRun':39293312298, 'originalJob':118199288801, 'originalArtifact':12207589449,
        'originalArchive':file_identity(archive, 128*1024**2), 'originalNativeSourceIdentity': NATIVE_IDENTITY,
        'originalQualification':file_identity(output/'qualification.json'), 'originalSource':file_identity(output/'source-inputs.json'),
        'historicalNormalNode':old['node'], 'originalBinaries':old['binaries'],
        'originalCompanions': qualification.companions(output, old),
        'selectedHost':host, 'nativeRecompiled':False, 'originalHostOverwritten':False,
        'currentDevelopmentCompilationClaimed':False, 'wholeNativeTupleClaimed':False,
        'freshOwnedStdAndApplicationRequired':True}
    write_json(output/'retrieval.json',value)
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare',action='store_true')
    parser.add_argument('--prepared',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.prepare:
        require(args.prepared is None,'rust-entropy-replay-prepare-only')
        prepare(args.output.resolve());return
    require(args.prepared is not None,'rust-entropy-replay-prepared-required')
    prepared=args.prepared.resolve(strict=True)
    old, products=verify(prepared)
    original_binaries=old['binaries']
    selected={**products,'latentd':prepared/'host/latentd'}
    # This diagnostic adapter supplies explicit mixed material identities. No old
    # receipt/file is rewritten and the normal qualifier keeps its strict path.
    def selected_materials(path):
        require(path == prepared,'rust-entropy-replay-fixed-prepared-only')
        receipt, originals=verify(path)
        require(receipt['binaries']==original_binaries,'rust-entropy-replay-original-drift')
        return read_json(prepared/'source-inputs.json'), {**receipt,
            'binaries':{name:file_identity(binary,512*1024**2) for name,binary in selected.items()}}, selected
    qualification.prepared_inputs=selected_materials
    result=qualification.qualify(prepared,args.output.resolve())
    materials={**read_json(prepared/'retrieval.json'), 'qualification':file_identity(args.output/'qualification.json'),
        'selectedBinaries':result['nativeBinaries'], 'freshSignedInvocations':result['signedInvocations']}
    write_json(args.output/'replay-materials.json',materials)
    print('Rust entropy:',result['status'],'invocations:',result['signedInvocations'])


if __name__ == '__main__': main()
