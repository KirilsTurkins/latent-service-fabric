"""Run actual TLS PAL source in isolated reference processes, never a guest claim."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.build_process import run_bounded
from tools.dev_workflow.common import require

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ('sdk/rust-standard-runtime/tls.rs', 'sdk/rust-standard-runtime/tests/tls_native.rs',
           'sdk/rust-standard-runtime/thread-abi.json', 'tools/run_rust_tls_reference.py')
CASES = (
    'a_child_or_replacement_cannot_install_another_roots_drain_registry',
    'borrowed_root_stack_prefix_has_exact_canonical_offsets',
    'denied_root_task_prevents_context_allocation_and_native_admission',
    'destroying_sentinel_cannot_be_erased_or_refunded_as_finished_work',
    'destructor_created_sibling_stays_owned_until_its_callback_finishes',
    'destructor_cycle_is_bounded_and_retains_its_context_and_owners',
    'each_entry_admits_before_initialization_and_uses_current_context_continuation',
    'failed_destructor_drain_retains_installed_stack_context_and_all_owners',
    'final_context_owner_settles_after_slot_clear_and_runtime_cleanup',
    'internal_storage_uses_system_and_physically_frees_before_settlement',
    'invalid_stack_ranges_and_size_overflow_reject_before_admission_and_allocation',
    'live_shadow_stack_and_tls_finish_do_not_clear_or_refund_the_final_rust_frame',
    'nested_retirement_cannot_refund_outer_live_destructor',
    'owned_stack_frees_actual_system_bytes_before_native_owner_settlement',
    'prepared_accepted_context_can_initialize_tls_during_close',
    'prepared_but_unstarted_context_retires_without_fake_execution',
    'root_bootstrap_admits_original_task_before_context_and_retains_it_through_final_epilogue',
    'root_destructor_work_is_drained_before_entries_and_original_task_retire',
    'root_pending_accepted_work_cannot_begin_tls_cleanup_or_refund_its_live_stack',
    'same_static_key_follows_independent_saved_canonical_context_values',
    'unstarted_stack_cannot_finish_or_be_reaped_as_completed_work',
    'unused_tls_has_no_context_or_ledger_allocation',
    'upstream_destroying_sentinel_preserves_reentrant_get_semantics',
)


def digest(path):
    raw = path.read_bytes()
    require(0 < len(raw) <= 16 * 1024 * 1024, 'rust-tls-reference-input-bound')
    return 'sha256:' + hashlib.sha256(raw).hexdigest()


def discovered(raw):
    text = raw.decode('utf-8')
    names = [line.removesuffix(': test') for line in text.splitlines() if line.endswith(': test')]
    require(len(names) == len(CASES) and set(names) == set(CASES)
            and text.rstrip().endswith(f'{len(CASES)} tests, 0 benchmarks'),
            'rust-tls-reference-case-set')
    return names


def passed(raw):
    require(raw.count(b'test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured;') == 1,
            'rust-tls-reference-case-not-executed')


def run(output: Path, rustc: Path):
    require(not output.exists() and not output.is_symlink(), 'rust-tls-reference-output-not-fresh')
    require(rustc.is_file() and not rustc.is_symlink(), 'rust-tls-reference-compiler')
    original = {name: digest(ROOT / name) for name in SOURCES}
    compiler = digest(rustc)
    output.mkdir(parents=True, mode=0o700)
    binary = output / ('tls-reference.exe' if os.name == 'nt' else 'tls-reference')
    deadline = time.monotonic() + 120
    used = 0

    def command(argv):
        nonlocal used
        remaining = deadline - time.monotonic()
        require(remaining > 0, 'rust-tls-reference-deadline')
        result = run_bounded(argv, ROOT, os.environ, remaining, 1024 * 1024 - used)
        used += len(result.stdout) + len(result.stderr)
        require(used < 1024 * 1024, 'rust-tls-reference-output-bound')
        return result.stdout

    receipt = {'schemaVersion': 'latent.rust.tls-source-reference.v1', 'status': 'failed',
        'sources': original, 'rustcDigest': compiler, 'caseCount': len(CASES), 'passed': [],
        'guestSysrootQualified': False, 'canonicalThreadsQualified': False,
        'nativeFiberRetirementQualified': False}
    try:
        version = command([str(rustc), '--version']).decode('utf-8').strip()
        require(version.startswith('rustc 1.97.1 ('), 'rust-tls-reference-compiler-version')
        receipt['rustcVersion'] = version
        command([str(rustc), '--edition=2024', '--test', str(ROOT / SOURCES[1]), '-o', str(binary)])
        receipt['executableDigest'] = digest(binary)
        names = discovered(command([str(binary), '--list']))
        for name in names:
            passed(command([str(binary), '--exact', name, '--test-threads=1']))
            receipt['passed'].append(name)
        require({name: digest(ROOT / name) for name in SOURCES} == original
                and digest(rustc) == compiler, 'rust-tls-reference-input-mutated')
        receipt['status'] = 'passed'
        return receipt
    finally:
        (output / 'reference.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--rustc', type=Path, required=True)
    args = parser.parse_args()
    result = run(args.output.resolve(), args.rustc.resolve())
    print(json.dumps({'status': result['status'], 'caseCount': len(result['passed']),
                      'qualification': 'native TLS source reference only'}))


if __name__ == '__main__':
    main()
