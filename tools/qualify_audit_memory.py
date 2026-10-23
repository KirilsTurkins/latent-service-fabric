"""One focused25-control connected Audit owner campaign, without guest builds.

This observes actual selected libtests and compiler checks of their shipping
consumers. It does not produce/relabel the immutable193-control host tuple or
qualify signed guest progress, opaque transport caches or OS worker stacks.
"""
from pathlib import Path
import argparse
import os
import re
import sys
import time
import tomllib

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_observation import build_environment
from tools import host_codec_wasmtime, result_owner_bytes
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity, inventory, source_identity
from tools.qualify_host_codec_native import Stages, exact_list, exact_result, materials
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, fresh, write_json

CONTROLS = (
    ('original-node-bank', 'latent-core', 'node_metadata::tests::', False, ('node_metadata::tests::original_node_metadata_identity_exact_ceiling_refusal_and_rollback_are_shared', 'node_metadata::tests::original_node_metadata_prepares_both_real_arc_allocations_before_payload_birth', 'node_metadata::tests::original_node_metadata_weak_headers_stay_paid_without_reviving_payload', 'node_metadata::tests::original_node_metadata_concurrent_last_strong_and_weak_refund_once', 'node_metadata::tests::original_node_fixed_and_transient_observations_conserve_one_admission_bank')),
    ('retired-envelope-reuse', 'latent-core', 'budget::host_memory::tests::original_native_envelope_reuses_only_retired_storage_without_refunding_capacity', True, ('budget::host_memory::tests::original_native_envelope_reuses_only_retired_storage_without_refunding_capacity',)),
    ('unobserved-retirement-refusal', 'latent-core', 'budget::host_memory::tests::native_envelope_refuses_unobserved_retirement_before_mutating_original_ledger', True, ('budget::host_memory::tests::native_envelope_refuses_unobserved_retirement_before_mutating_original_ledger',)),
    ('audit-owned-graph', 'latent-audit', 'durable::memory::tests::', False, ('durable::memory::tests::audit_original_envelope_precedes_copy_and_abandoned_preparation_does_not_invent_storage', 'durable::memory::tests::audit_original_arc_last_concurrent_clones_keep_payload_and_billing_headers_paid', 'durable::memory::tests::audit_original_box_unwind_destroys_actual_payload_before_any_physical_refund', 'durable::memory::tests::audit_confirmation_failure_unwind_keeps_payload_paid_and_refunds_once', 'durable::memory::tests::audit_borrowed_graph_bound_keeps_original_json_limits_and_measures_canonical_capacity')),
    ('audit-node-worker', 'latent-audit', 'durable::worker::node_memory_tests::', False, ('durable::worker::node_memory_tests::audit_default_fixed_backing_fits_the_original_eight_mib_node_ceiling', 'durable::worker::node_memory_tests::audit_funded_birth_refuses_before_filesystem_on_capacity_or_ceiling_mismatch', 'durable::worker::node_memory_tests::page_record_preflight_accounts_actual_original_graph_before_decode_and_rolls_back_refusal', 'durable::worker::node_memory_tests::live::funded_pending_and_returned_ack_retain_original_transient_memory_until_real_drop', 'durable::worker::node_memory_tests::live::funded_read_only_page_clones_share_backing_and_keep_node_capacity_after_close', 'durable::worker::node_memory_tests::live::funded_unjoined_worker_retains_exact_original_quarantine_after_body_completion', 'durable::worker::node_memory_tests::live::activation_audit_custody_never_moves_to_equal_foreign_budget_or_persistent_node_history', 'durable::worker::node_memory_tests::live::funded_observation_capacity_refusal_preserves_original_state_and_lossy_drop_counter', 'durable::worker::node_memory_tests::live::funded_pending_read_only_views_share_actual_graph_through_teardown_and_last_clone')),
    ('original-broker-node-bank', 'latent-capabilities', 'broker::ownership::node_metadata_tests::', False, ('broker::ownership::node_metadata_tests::original_node_bank_and_logical_broker_metadata_are_distinct_conserved_observations', 'broker::ownership::node_metadata_tests::original_metadata_swap_refuses_mismatched_ceiling_and_prior_or_retained_zero_charge')),
    ('required-before-copy-refusal', 'latent-capabilities', 'broker::tests::audit::required_audit_native_refusal_precedes_dispatch_and_preserves_all_original_owners', True, ('broker::tests::audit::required_audit_native_refusal_precedes_dispatch_and_preserves_all_original_owners',)),
    ('audit-ack-error-retirement', 'latent-audit', 'durable::worker::run::tests::ack_admission_refusal_repairs_original_pending_finish_and_actual_abandon_drains', True, ('durable::worker::run::tests::ack_admission_refusal_repairs_original_pending_finish_and_actual_abandon_drains',)),
)

RECIPE = ('.github/workflows/audit-memory-owner.yml',
          'tools/qualify_audit_memory.py', 'tools/tests/test_audit_memory_programme.py',
          'tools/ci/suites.json')


def control_inventory():
    names = tuple(case for _, _, _, _, cases in CONTROLS for case in cases)
    require(len(CONTROLS) == 8 and len({row[0] for row in CONTROLS}) == 8
            and len(names) == len(set(names)) == 25, 'audit-memory-closed25-controls')
    return names


def selected_arguments(cargo, group):
    _, package, selector, exact, expected = group
    require(package in {'latent-core', 'latent-audit', 'latent-capabilities'}
            and bool(expected) and (not exact or expected == (selector,)),
            'audit-memory-closed-package-selector')
    return (*cargo, 'test', '--locked', '-p', package, '--lib', selector,
            '--', *(('--exact',) if exact else ()))


def inputs():
    return {'source': source_identity(ROOT), 'materials': dict(sorted({
        **materials(ROOT), **{name: file_identity(ROOT / name) for name in RECIPE}}.items()))}


def qualify(output: Path, revision: str):
    require(sys.platform == 'linux' and re.fullmatch('[0-9a-f]{40}', revision),
            'audit-memory-real-linux-source')
    output = fresh(output)
    record = {'schemaVersion': 'latent.audit.memory-native.v1', 'status': 'incomplete',
              'sourceRevision': revision, 'controlCount': 25,
              'signedGuestQualification': False, 'fullAllocationClosureQualified': False,
              'guestSourceCompiled': False, 'historical193ProductsRebuilt': False,
              'opaqueTransportCachesQualified': False, 'osWorkerStacksQualified': False}
    stages, primary, stage = None, False, 'prebuild-source-and-original-vendor-inputs'
    try:
        control_inventory()
        host_codec_wasmtime.verify(ROOT)
        result_owner_bytes.verify(ROOT)
        require(tomllib.loads((ROOT / 'rust-toolchain.toml').read_text(encoding='utf-8'))
                ['toolchain']['channel'] == '1.97.1', 'audit-memory-pinned-toolchain')
        before = inputs()
        write_json(output / 'source-inputs.json', before)
        environment = build_environment(output)
        environment.update(CARGO_TARGET_DIR=str(Path(os.environ.get('CARGO_TARGET_DIR', ROOT / 'target')).resolve()),
            RUSTUP_TOOLCHAIN='1.97.1', CARGO_BUILD_JOBS='2', CARGO_INCREMENTAL='0',
            CARGO_PROFILE_DEV_DEBUG='0', CARGO_PROFILE_TEST_DEBUG='0',
            CARGO_PROFILE_DEV_DEBUG_ASSERTIONS='true', CARGO_PROFILE_TEST_DEBUG_ASSERTIONS='true',
            CARGO_PROFILE_DEV_OVERFLOW_CHECKS='true', CARGO_PROFILE_TEST_OVERFLOW_CHECKS='true')
        stages = Stages(Commands(ROOT, output, environment,
                                deadline_seconds=1320, command_seconds=1200), output)
        stage = 'exact-source-revision'
        require(stages.run(stage, 'git', 'rev-parse', 'HEAD').decode().strip() == revision,
                'audit-memory-source-revision-mismatch')
        stage = 'pinned-rust-version'
        compiler = stages.run(stage, 'rustc', '--version').decode().strip()
        require(compiler.startswith('rustc 1.97.1 ('), 'audit-memory-actual-rust-version')
        cargo = ('cargo', '--config', ROOT / '.cargo/managed-guest.toml')
        for group in CONTROLS:
            name, _, _, _, expected = group
            arguments = selected_arguments(cargo, group)
            stage = name + '-list'
            exact_list(stages.run(stage, *arguments, '--list'), expected)
            stage = name + '-run'
            exact_result(stages.run(stage, *arguments, '--test-threads=1'), expected)
        # Compile changed shipping consumers and RPC ownership APIs only. This
        # does not link/publish five host products or execute broader test suites.
        stage = 'changed-rpc-cli-node-consumer-check'
        stages.run(stage, *cargo, 'check', '--locked', '-p', 'latent-wire',
                   '-p', 'latent', '-p', 'latentd')
        stage = 'final-identical-source-and-recipe'
        require(before == inputs(), 'audit-memory-source-or-recipe-changed')
        record.update(status='passed', compiler=compiler, inputs=before,
            controls={name: list(cases) for name, _, _, _, cases in CONTROLS},
            ignoredControls=0, commands=stages.records,
            actualControlExecution=True, changedShippingConsumersCompileChecked=True)
        write_json(output / 'receipt.json', record)
        return record
    except BaseException:
        primary = True
        record.update(status='failed', failedStage=stage,
                      currentStage=stages.current if stages else None,
                      commands=stages.records if stages else [])
        raise
    finally:
        try:
            write_json(output / 'result.json', record)
            inventory(output, maximum_files=256, maximum_bytes=32 * 1024 * 1024,
                      deadline=time.monotonic() + 60)
        except BaseException:
            if not primary:
                raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--source-commit', required=True)
    args = parser.parse_args()
    qualify(args.output, args.source_commit)
