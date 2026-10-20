"""Authenticate the sole closed path_open result correction; never grant storage."""
import hashlib
from pathlib import Path
from tools.phase2_operator_process import require

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL_SHA256 = '32ecb6bd1d893d033faa08406478023bec590983c2f0af9af3694c82adbf7ab8'
OLD_OPEN = b'  (func (export "path_open") (param i32 i32 i32 i32 i32 i64 i64 i32 i32) (result i32) i32.const 76)'
CURRENT_OPEN = OLD_OPEN.replace(b'const 76)', b'const 52)')
ADAPTER_CASE = 'go_closed_filesystem::exact_closed_path_open_is_enosys_without_changing_discovery_or_other_authority'


def adapter_sources(root=ROOT):
    current = (root / 'sdk/go-guest/runtime/deny-wasi.wat').read_bytes()
    require(len(current) <= 65536 and current.count(CURRENT_OPEN) == 1 and OLD_OPEN not in current,
            'Go-closed-path-open-exact-shape')
    original = current.replace(CURRENT_OPEN, OLD_OPEN, 1)
    require(hashlib.sha256(original).hexdigest() == ORIGINAL_SHA256,
            'Go-closed-adapter-unrelated-source-drift')
    return original, current


def strict_scratch_result(record):
    require(record.get('status') == 'passed' and record.get('language') == 'go'
            and record.get('filesystemGrantsAdded') is False and record.get('scratchStorageImplemented') is False,
            'Go-scratch-original-qualified-source-required')
    scratch = record['scratch']
    require(scratch.get('status') == 'passed' and scratch.get('language') == 'go'
            and scratch.get('allErrorsAreUnsupported') is True
            and [row['mode'] for row in scratch['cases']] == ['open', 'create', 'temp'],
            'Go-scratch-all-three-concrete-unsupported-required')
    for row in scratch['cases']:
        require(row['observation']['category'] == 'path-error|errno=52'
                and row['observation']['unsupported'] is True
                and row['invocation']['decoded'] == [{'ok': 'scratch|go|path-error|errno=52|fresh=1'}],
                'Go-scratch-standard-errors-Is-and-exact-ENOSYS-required')
    require(record['inherited']['originalInvocations'] == 27 and record['invocations'] == 33,
            'Go-scratch-original-normal-and-six-required')
    return {'status': 'passed', 'language': 'go', 'apiResults': [
        {'operation': operation, 'errno': 52, 'errorsIsUnsupported': True}
        for operation in ['os.Open', 'os.OpenFile', 'os.CreateTemp']],
        'originalNormalInvocations': record['inherited']['originalInvocations'],
        'totalInvocations': record['invocations'], 'filesystemGrantsAdded': False,
        'scratchStorageImplemented': False, 'allFilesystemApisQualified': False,
        'fullTicketQualification': False}
