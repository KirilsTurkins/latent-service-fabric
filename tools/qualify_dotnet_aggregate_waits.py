"""One normal published Polly NativeAOT build and fourteen signed WaitAll outcomes."""
from pathlib import Path
import hashlib
import json
import sys

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

MAX_PUBLIC = 256 * 1024**2
MAX_DOCUMENT = 1024**2
# This same closed list is used by the workflow. Application/signer workspaces,
# installed packages, private node configuration and key files are not selected.
PUBLIC_PATTERNS = (
    'native/native-products.json', 'native/source-inputs.json', 'native/retrieval.json',
    'tools/INSTALL-COMPLETE.json', 'tools/runtime-inputs.json', 'tools/wasi-sdk.json',
    'tools/logs/*.stdout.txt', 'tools/logs/*.stderr.txt',
    'programme/qualified.json', 'programme/FAILED.json', 'programme/capture.json',
    'programme/build/*.json', 'programme/build/component.wasm', 'programme/build/native-aot-original.wasm',
    'programme/build/derived-*.dll', 'programme/build/logs/*.stdout.txt', 'programme/build/logs/*.stderr.txt',
    'programme/build/package/*.json', 'programme/build/package/*.wasm',
    'programme/node/*.json', 'programme/node/node-stderr.txt',
    'programme/node/commands/logs/*.stdout.txt', 'programme/node/commands/logs/*.stderr.txt',
    'programme/node/controls/*.json', 'programme/node/signed/my-greeting/build-observation.json',
    'programme/node/signed/release-set.json')


def admit_evidence(root):
    root = Path(root).absolute()
    record = root/'evidence-admission.json'
    value = {'schemaVersion': 'latent.dotnet.aggregate-wait.evidence-admission.v1', 'status': 'failed'}
    try:
        if not root.is_dir() or root.is_symlink():
            raise ValueError('evidence-root')
        files = sorted({path for pattern in PUBLIC_PATTERNS for path in root.glob(pattern)})
        if not 1 <= len(files) <= 1024:
            raise ValueError('evidence-count')
        total = 0
        identities = {}
        for path in files:
            relative = path.relative_to(root)
            if (not path.is_file() or path.is_symlink()
                    or any(root.joinpath(*relative.parts[:index]).is_symlink() for index in range(len(relative.parts)))
                    or not 0 <= path.stat().st_size <= 64*1024**2):
                raise ValueError('evidence-file')
            data = path.read_bytes()
            total += len(data)
            if total > MAX_PUBLIC-MAX_DOCUMENT:
                raise ValueError('evidence-total')
            identities[relative.as_posix()] = {'bytes': len(data), 'sha256': 'sha256:'+hashlib.sha256(data).hexdigest()}
        value.update(status='passed', files=identities, payloadBytes=total,
            uploadUnionMaximumBytes=MAX_PUBLIC)
    finally:
        data = (json.dumps(value, sort_keys=True, separators=(',', ':'))+'\n').encode('utf-8')
        if len(data) > MAX_DOCUMENT:
            raise ValueError('evidence-admission-document')
        record.write_bytes(data)
    return value


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('native', 'tools'):
        parser.add_argument('--'+name, type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--admit-evidence', action='store_true')
    args = parser.parse_args()
    if args.admit_evidence:
        if args.native is not None or args.tools is not None:
            parser.error('evidence admission does not accept compiler or native inputs')
        print(admit_evidence(args.output)['status'])
    else:
        if args.native is None or args.tools is None:
            parser.error('qualification requires --native and --tools')
        from tools.qualify_dotnet_finite_waits import qualify
        print(qualify(args.native, args.tools, args.output, aggregate=True)['status'])
