"""One source-bound ordinary native host codec programme; no guest engine build."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time
import tomllib
if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.build_observation import build_environment
from tools.build_process import BuildProcessError
from tools import host_codec_wasmtime as codec_wasmtime
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity, inventory, source_identity
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, fresh, write_json

CONTROLS = (('original-host-memory',
  'latent-core',
  'host_memory',
  ('budget::descendants::tests::host_memory_resize_confirms_parent_peak_and_retains_terminal_child_capacity',
   'budget::host_memory::tests::actual_native_owner_keeps_capacity_after_terminal_report_and_settles_once',
   'budget::host_memory::tests::failed_pending_replacement_refunds_only_unallocated_capacity',
   'budget::host_memory::tests::growing_overlap_competes_before_allocation_and_shrink_keeps_peak',
   'budget::host_memory::tests::native_and_linear_memory_compete_before_allocation_and_failed_preparations_roll_back',
   'budget::host_memory::tests::partial_confirmation_keeps_pending_capacity_without_inventing_allocated_peak')),
 ('result-owner',
  'latent-core',
  'result_payload',
  ('result_payload::tests::a_foreign_reservation_cannot_certify_the_original_budget',
   'result_payload::tests::accounted_payload_clone_and_transport_hold_the_same_bytes_and_charge',
   'result_payload::tests::legacy_constructor_preserves_capacity_and_comparison',
   'result_payload::tests::owner_allocation_refusal_releases_original_storage_and_charge')),
 ('result-wire',
  'latent-rpc',
  'result_messages',
  ('result_messages::tests::external_sliced_wire_backing_is_copied_before_capacity_validation',
   'result_messages::tests::original_generated_results_cross_encode_defaults_and_all_fields',
   'result_messages::tests::original_generated_results_repeated_singular_unknown_and_malformed_fields',
   'result_messages::tests::result_message_local_clones_capacity_clear_and_transport_keep_original_owner')),
 ('result-capacity',
  'latent-rpc',
  'result_payload_capacity',
  ('phase4::bounds::result_capacity_tests::result_payload_capacity_is_checked_without_trusting_only_length',)),
 ('actual-host-codec',
  'latent-wasmtime',
  'values::tests::host_memory::',
  ('values::tests::host_memory::host_codec_actual_malformed_string_lift_keeps_the_original_envelope',
   'values::tests::host_memory::host_codec_actual_pending_call_cancellation_keeps_envelope_until_native_drop',
   'values::tests::host_memory::host_codec_encoder_refuses_original_memory_without_losing_live_values',
   'values::tests::host_memory::host_codec_failed_and_abandoned_lifts_keep_conservative_capacity_attribution',
   'values::tests::host_memory::host_codec_input_uses_original_memory_and_drops_values_before_refund',
   'values::tests::host_memory::host_codec_original_refusal_cannot_retry_the_legacy_allocator',
   'values::tests::host_memory::host_codec_rejection_oracle_preserves_original_typed_error_precedence',
   'values::tests::host_memory::host_codec_scalar_and_numeric_stack_formatting_keep_original_bytes_and_small_peak',
   'values::tests::host_memory::host_codec_tiny_dynamic_string_and_declared_result_preserve_normal_64mib_profile')),
 ('actual-dynamic-allocation-hook',
  'latent-wasmtime',
  'values::tests::dynamic_memory::',
  ('values::tests::dynamic_memory::actual_dynamic_declared_tiny_result_fits_original_one_mib_without_maximum_escrow',
   'values::tests::dynamic_memory::actual_lift_refusal_retains_original_memory_bytes_error_and_does_not_allocate_string',
   'values::tests::dynamic_memory::actual_nested_names_flags_and_variant_box_hold_original_memory_until_values_die',
   'values::tests::dynamic_memory::actual_parameter_copy_refunds_and_cancelled_post_return_cannot_credit_a_new_result',
   'values::tests::dynamic_memory::actual_partial_failed_lift_reports_only_allocated_tree_and_retires_after_native_unwind',
   'values::tests::dynamic_memory::actual_utf8_utf16_latin1_prepass_preserves_exact_original_fuel_and_capacity')),
 ('raw-input-lifetime',
  'latent-wasmtime',
  'backend::input::tests::',
  ('backend::input::tests::actual_owned_field_is_destroyed_before_its_raw_guard_refunds',
   'backend::input::tests::completion_abandonment_and_poll_unwind_retire_after_actual_future_destruction',
   'backend::input::tests::error_before_guest_dispatch_releases_input_without_inventing_guest_start',
   'backend::input::tests::raw_input_admits_actual_spare_capacity_until_storage_destruction_and_refunds_refusal')),
 ('result-lifetime',
  'latent-wasmtime',
  'backend::result_lifetime_tests::',
  ('backend::result_lifetime_tests::native_errors_release_while_the_actual_cleanup_helper_still_owns_runtime_and_permit',
   'backend::result_lifetime_tests::successful_classification_and_unwind_keep_the_same_final_drop_order')),
 ('original-accounting',
  'latent-wasmtime',
  'host::accounting::tests::',
  ('host::accounting::tests::deadlines::legacy_precise_token_is_validated_without_extending_its_unix_projection',
   'host::accounting::tests::deadlines::relative_ceiling_after_a_wall_jump_preserves_the_managers_grant_projection',
   'host::accounting::tests::deadlines::shared_ledger_keeps_submillisecond_deadline_without_a_second_deadline_token',
   'host::accounting::tests::deadlines::token_only_deadline_survives_a_forward_wall_jump',
   'host::accounting::tests::diagnostic::execution_hook_records_the_precise_deadline_and_the_actual_expiry_check_sample',
   'host::accounting::tests::failed_growth_does_not_charge_a_provisional_memory_peak',
   'host::accounting::tests::fallback_is_one_local_ledger_per_invocation_and_uses_one_sample',
   'host::accounting::tests::invalid_owners_grants_and_runtime_counter_increases_fail_closed',
   'host::accounting::tests::legacy_deadline_token_is_used_without_renewing_its_relative_grant',
   'host::accounting::tests::log_reservations_refund_and_terminal_reports_cannot_overwrite_host_charges',
   'host::accounting::tests::original_clock_sample_and_tighter_request_deadline_survive_wall_adjustment',
   'host::accounting::tests::phase3_managed_execution_keeps_original_ledger_and_rejects_unmanaged_opt_in',
   'host::accounting::tests::runtime_observation::competing_fuel_charge_cannot_publish_the_failed_observations_memory_peak',
   'host::accounting::tests::runtime_observation::concurrent_child_admission_requires_native_fuel_reconciliation_before_next_host_call',
   'host::accounting::tests::runtime_observation::finalized_ledger_cannot_advance_either_local_watermark_even_for_zero_fuel',
   'host::accounting::tests::runtime_observation::invalid_native_observations_leave_both_watermarks_and_ledger_unchanged',
   'host::accounting::tests::runtime_observation::native_fuel_adjustments_do_not_double_charge_child_work_or_refunds',
   'host::accounting::tests::runtime_observation::repeated_lower_memory_observations_keep_the_confirmed_peak_and_log_reservation',
   'host::accounting::tests::shares_the_original_ledger_and_charges_only_new_fuel_deltas',
   'host::accounting::tests::stricter_cancellation_monotonic_deadline_is_retained_with_a_supplied_ledger')),
 ('child-capacity',
  'latent-node',
  'result_transfer_counts_unused_capacity_and_bounds_metadata_traversal',
  ('activation_manager::local_service::result::tests::result_transfer_counts_unused_capacity_and_bounds_metadata_traversal',)),
 ('c-public-async-type',
  'latent-component-threading',
  'c_public_lift_requires_declared_async_type_with_original_sync_core_abi',
  ('component::c::tests::c_public_lift_requires_declared_async_type_with_original_sync_core_abi',)),
 ('c-public-sync-abi',
  'latent-component-threading',
  'c_declared_async_effect_does_not_enable_callback_or_async_core_abi',
  ('component::c::tests::c_declared_async_effect_does_not_enable_callback_or_async_core_abi',)),
 ('journal-result-retirement',
  'latent-node',
  'bounded_journal_copy_preserves_declared_error_and_retires_child_only_after_last_source_drop',
  ('journal::tests::accounted_declared_result::bounded_journal_copy_preserves_declared_error_and_retires_child_only_after_last_source_drop',)),
 ('ordinary-backend',
  'latent-wasmtime',
  'ordinary_backend_codec_reports_original_peak_and_result_outlives_store_cleanup',
  ('backend::readiness::tests::invocation::ordinary_backend_codec_reports_original_peak_and_result_outlives_store_cleanup',)),
 ('actual-native-table-owner',
  'latent-wasmtime',
  'host::native_table_tests::',
  ('host::native_table_tests::actual_typescript_fixed_tables_debit_original_memory_and_outlive_limiter_destruction',
   'host::native_table_tests::actual_table_refusal_keeps_exact_original_memory_error_and_no_retained_owner',
   'host::native_table_tests::actual_dynamic_table_growth_pays_exact_old_new_overlap_and_keeps_function_cells',
   'host::native_table_tests::actual_dynamic_table_refused_replacement_keeps_original_cells_capacity_and_owner',
   'host::native_table_tests::actual_tiny_and_zero_tables_do_not_reserve_declared_maximum_capacity',
   'host::native_table_tests::actual_preceding_linear_allocation_is_confirmed_before_table_memory_admission',
   'host::native_table_tests::actual_original_element_and_table_count_caps_still_refuse_without_extra_owners',
   'host::native_table_tests::actual_pooled_table_slot_keeps_owner_through_user_data_then_real_flush',
   'host::native_table_tests::actual_batched_pool_table_keeps_original_owner_until_decommit_queue_destruction')),
 ('actual-native-store-owner',
 'latent-wasmtime',
 'host::native_store_tests::',
 ('host::native_store_tests::actual_store_box_refusal_preserves_original_error_and_exactly_once_data_drop',
  'host::native_store_tests::actual_dummy_instance_refusal_rolls_back_box_map_factory_and_user_data',
  'host::native_store_tests::actual_store_core_and_component_owners_outlive_user_data_until_physical_cleanup',
  'host::native_store_tests::actual_into_data_frees_inner_and_factory_before_returning_once_owned_data',
  'host::native_store_tests::actual_user_data_unwind_cannot_refund_the_still_allocated_store',
  'host::native_store_tests::actual_instance_map_overlap_refusal_preserves_prior_instance_and_fresh_reuse',
  'host::native_store_tests::actual_passive_segment_backing_remains_owned_until_guest_elem_drop',
  'host::native_store_tests::actual_tiny_component_still_fits_original_one_mib_and_one_billion_fuel',
  'host::native_store_tests::actual_cancelled_lift_preserves_store_owners_and_cannot_credit_another_live_store',
  'host::native_store_tests::actual_factory_arc_layout_includes_overalignment_and_both_pinned_counters')),
 ('closed-guest-trap-diagnostics',
 'latent-wasmtime',
 'containment::tests::backend_trap_labels_match_the_public_closed_classification',
 ('containment::tests::backend_trap_labels_match_the_public_closed_classification',)) ,
 ('actual-native-registry-owner',
 'latent-wasmtime',
 'host::native_registry_tests::',
 ('host::native_registry_tests::actual_registry_all_four_preparation_refusals_preserve_prior_modules_and_fresh_retry',
  'host::native_registry_tests::actual_registry_duplicate_module_has_no_new_registry_backing',
  'host::native_registry_tests::actual_registry_foreign_engine_refusal_precedes_all_registry_admission',
  'host::native_registry_tests::actual_registry_component_sparse_module_indices_preserve_both_original_results')),
 ('actual-native-funcrefs-owner',
 'latent-wasmtime',
 'host::native_func_refs_tests::',
 ('host::native_func_refs_tests::actual_funcrefs_growth_preserves_old_guest_calls_at_original_memory_and_fuel_limits',
  'host::native_func_refs_tests::actual_funcrefs_all_four_staged_refusals_preserve_roots_fill_and_original_error',
  'host::native_func_refs_tests::actual_funcrefs_shared_linker_root_survives_linker_drop_until_store_destruction',
  'host::native_func_refs_tests::actual_funcrefs_instance_pre_pair_refusal_preserves_prior_instance_and_retry',
  'host::native_func_refs_tests::actual_funcrefs_default_lookup_preserves_original_admission_error')),
 ('c-ready-handoff',
 'latent-component-threading',
 'c_ready_handoff_',
 ('component::c::tests::c_ready_handoff_canonical_requires_ready_aware_promote',
  'component::c::tests::c_ready_handoff_final_graph_refuses_resume_or_mismatched_target')),
 ('resource-substitutions',
  'latent-wasmtime',
  'host::native_resource_types_tests::',
  ('host::native_resource_types_tests::actual_resource_types_pre_and_function_metadata_outlive_store_and_factory', 'host::native_resource_types_tests::actual_resource_types_both_admission_refusals_preserve_prior_instance_and_retry', 'host::native_resource_types_tests::actual_resource_types_independent_stores_cannot_refund_live_foreign_metadata', 'host::native_resource_types_tests::actual_resource_types_concurrent_metadata_clones_release_original_owner_once', 'host::native_resource_types_tests::actual_resource_types_zero_resource_tiny_call_keeps_original_one_mib_and_billion_fuel')),
 ('actual-linear-allocation-notifications',
 'latent-wasmtime',
 'host::native_linear_memory_tests::',
 ('host::native_linear_memory_tests::actual_linear_memory_is_confirmed_before_subsequent_native_instance_allocations',
  'host::native_linear_memory_tests::actual_linear_creator_failure_rolls_back_without_confirming_unallocated_pages',
  'host::native_linear_memory_tests::actual_linear_growth_confirms_success_and_failed_growth_preserves_prior_peak')),
 ('native-thread-audit-codec',
 'latent-audit',
 'native_thread_audit_',
 ('durable::tests::capability::native_thread_audit_encodes_exact_grant_and_host_completion_without_changing_default_abi',
  'durable::tests::capability::native_thread_audit_refuses_other_versions_operations_and_resource_classes',
  'durable::tests::capability::native_thread_audit_retains_identity_outcome_and_redaction_boundaries')),
 ('retained-activation-context',
 'latent-wasmtime',
 'host::owned_context::tests::',
 ('host::owned_context::tests::web_asset_identity_comes_from_the_prepared_revision_not_caller_metadata',
  'host::owned_context::tests::unselected_or_mismatched_execution_cannot_spoof_the_reserved_web_identity',
  'host::owned_context::tests::web_identity_map_entry_is_charged_before_context_ownership_transfer',
  'host::owned_context::tests::validated_context_moves_every_field_and_ordinary_backing_buffer',
  'host::owned_context::tests::capacity_threshold_is_inclusive_and_excess_has_a_hard_postcondition',
  'host::owned_context::tests::spare_capacity_does_not_change_the_existing_logical_admission_boundary',
  'host::owned_context::tests::excessive_values_keep_map_nodes_and_ordinary_keys_in_place',
  'host::owned_context::tests::excessive_keys_rebuild_only_their_map_and_preserve_values_and_order',
  'host::owned_context::tests::retained_context_uses_original_memory_until_drop_and_rolls_back_refused_admission',
  'host::owned_context::tests::retained_context_bound_excludes_discarded_scaffolding_and_caller_web_identity',
  'host::owned_context::tests::retained_context_keeps_legacy_profile_unaccounted_and_arithmetic_checked')))

PRODUCTS = ('latent', 'latentd', 'examples/package', 'examples/capsule_contracts', 'examples/capsule_authoring')
RECIPE = ('.github/workflows/host-codec-memory.yml', '.cargo/managed-guest.toml',
    'tools/qualify_host_codec_native.py', 'tools/tests/test_host_codec_native.py',
    'tools/toolchain.toml', 'tools/rust_capsule_build.py', 'tools/build_observation.py',
    'tools/build_process.py', 'tools/build_process_linux.py', 'tools/build_process_signals.py',
    'tools/phase2_operator_process.py', 'tools/phase3_resource_identity.py',
    'tools/phase3_resource_profile.py', 'tools/rust_capsule_project.py', 'tools/build_snapshot.py',
    'tools/host_codec_wasmtime.py',
    'crates/vendor/wasmtime/UPSTREAM.latent.json', 'crates/vendor/wasmtime/latent-dynamic-memory.patch',
    'crates/vendor/wasmtime/README.latent.md',
    'examples/echo-contract/capsule.json', 'examples/package-format/capsule/manifest.json',
    'examples/package-format/capsule/config.json')

def exact_list(raw: bytes, expected: tuple[str, ...]) -> None:
    names = re.findall(rb'^([^\r\n]+): test$', raw, re.M)
    actual = [name.decode('utf-8') for name in names]
    require(bool(expected) and len(set(expected)) == len(expected)
            and len(actual) == len(expected) and set(actual) == set(expected), 'host-codec-test-list-mismatch')

def exact_result(raw: bytes, expected: tuple[str, ...]) -> None:
    names = re.findall(rb'^test ([^\r\n]+) \.\.\. ok$', raw, re.M)
    actual = [name.decode('utf-8') for name in names]
    summary = f'test result: ok. {len(expected)} passed; 0 failed; 0 ignored;'.encode()
    require(len(actual) == len(expected) and set(actual) == set(expected)
            and raw.count(summary) == 1 and b'... ignored' not in raw, 'host-codec-test-result-mismatch')

# Inspected fixed reasons in the pinned, source-bound Linux runner. Never emit
# exception text or suggest discarded timeout/overflow captures were retained.
BUILD_REASONS = frozenset(('command-invalid', 'command-context-invalid',
    'command-environment-invalid', 'command-timeout-invalid', 'command-output-limit-invalid',
    'python-version-unsupported', 'process-main-thread-required', 'process-platform-unsupported',
    'command-deadline', 'command-output-limit', 'command-exit', 'process-cleanup',
    'command-failed', 'child-reaper-unsupported', 'process-ownership'))

class Stages:
    """Pre-record argv; retain real streams only when the runner returns them."""
    def __init__(self, commands, output: Path):
        self.commands, self.output, self.records = commands, output, []
        self.current = None
    def snapshot(self, name: str, value) -> None:
        # write_json uses exclusive creation. Replace only our prior snapshot
        # inside the new private output directory; no shared runner is changed.
        pending = self.output/(name+'.next')
        write_json(pending, value)
        pending.replace(self.output/name)
    def run(self, stage: str, *argv) -> bytes:
        ordinal = len(self.commands.records)
        self.current = {'ordinal':ordinal, 'stage':stage, 'argv':[str(v) for v in argv],
                        'status':'running', 'streamsRetained':False}
        self.snapshot('current-stage.json', self.current)
        try:
            return self.commands.run(stage, *argv)
        except BuildProcessError as error:
            reason = error.reason if error.reason in BUILD_REASONS else 'unclassified-build-process-error'
            self.current.update(status='failed', reason=reason)
            self.snapshot('current-stage.json', self.current)
            raise
        finally:
            if len(self.commands.records) > ordinal:
                row = dict(self.commands.records[ordinal])
                row['argv'] = [str(value) for value in argv]
                row['logs'] = {stream: {'path': f'logs/{ordinal:02d}-{stage}.{stream}.txt',
                    **file_identity(self.output/'logs'/f'{ordinal:02d}-{stage}.{stream}.txt', 4*1024**2)}
                    for stream in ('stdout', 'stderr')}
                self.records.append(row)
                self.current.update(status='passed' if row['exitCode']==0 else 'failed',
                                    streamsRetained=True, exitCode=row['exitCode'])
                self.snapshot('commands.json', self.records)
                self.snapshot('current-stage.json', self.current)

def materials(root: Path) -> dict:
    result = {name: file_identity(root/name) for name in RECIPE}
    for directory, maximum_files, maximum_bytes in (
        ('wit',2048,8*1024**2),('schemas',256,4*1024**2),
        ('examples/echo-contract/wit',128,1024**2),('api/proto',128,1024**2)):
        observed = inventory(root/directory, maximum_files=maximum_files,
            maximum_bytes=maximum_bytes, deadline=time.monotonic()+30)
        for row in observed['files']:
            name = directory+'/'+row['path']
            require(name not in result, 'host-codec-material-duplicate')
            result[name] = {'sha256':row['sha256'], 'bytes':row['bytes']}
    return dict(sorted(result.items()))

def qualify(output: Path, revision: str) -> dict:
    require(re.fullmatch('[0-9a-f]{40}', revision) is not None, 'host-codec-source-revision')
    require(sys.platform == 'linux', 'host-codec-linux-owner-required')
    names = [name for _,_,_,cases in CONTROLS for name in cases]
    require(len(CONTROLS) == 24 and len({row[0] for row in CONTROLS}) == 24
            and len(names) == len(set(names)) == 114, 'host-codec-control-inventory')
    output = fresh(output)
    codec_wasmtime.verify(ROOT)
    before, inputs = source_identity(ROOT), materials(ROOT)
    write_json(output/'source-inputs.json', {'native':before, 'materials':inputs})
    require(tomllib.loads((ROOT/'rust-toolchain.toml').read_text())['toolchain']['channel'] == '1.97.1', 'host-codec-rust-pin')
    environment = build_environment(output)
    target = Path(os.environ.get('CARGO_TARGET_DIR', ROOT/'target')).resolve()
    environment.update(CARGO_TARGET_DIR=str(target), RUSTUP_TOOLCHAIN='1.97.1',
        CARGO_BUILD_JOBS='2', CARGO_INCREMENTAL='0', CARGO_PROFILE_DEV_DEBUG='0', CARGO_PROFILE_TEST_DEBUG='0',
        CARGO_PROFILE_DEV_DEBUG_ASSERTIONS='true', CARGO_PROFILE_TEST_DEBUG_ASSERTIONS='true',
        CARGO_PROFILE_DEV_OVERFLOW_CHECKS='true', CARGO_PROFILE_TEST_OVERFLOW_CHECKS='true')
    stages = Stages(Commands(ROOT,output,environment,deadline_seconds=1320,command_seconds=1200), output)
    try:
        observed_revision = stages.run('source-revision','git','rev-parse','HEAD').decode().strip()
        require(observed_revision == revision, 'host-codec-source-revision-mismatch')
        compiler = stages.run('rust-version','rustc','--version').decode().strip()
        require(compiler.startswith('rustc 1.97.1 ('), 'host-codec-rust-version')
        cargo = ('cargo','--config',ROOT/'.cargo/managed-guest.toml')
        stages.run('normal-host-build',*cargo,'build','--locked','-p','latent','-p','latentd','--bins',
            '-p','latent-packaging','--example','package','--example','capsule_contracts',
            '-p','latent-policy','--example','capsule_authoring')
        for stage, package, needle, expected in CONTROLS:
            args = (*cargo,'test','--locked','-p',package,'--lib',needle,'--')
            exact_list(stages.run(stage+'-list',*args,'--list'), expected)
            exact_result(stages.run(stage+'-run',*args,'--test-threads=1'), expected)
        require(before == source_identity(ROOT) and inputs == materials(ROOT), 'host-codec-source-changed')
        products, owned = {}, output/'native-binaries'
        owned.mkdir(mode=0o700)
        for name in PRODUCTS:
            source = target/'debug'/name
            identity = file_identity(source,512*1024**2)
            destination = owned/name.replace('/','-')
            shutil.copyfile(source,destination); destination.chmod(0o700)
            require(file_identity(source,512*1024**2) == identity == file_identity(destination,512*1024**2), 'host-codec-product-capture-changed')
            products[name] = identity
        record = {'schemaVersion':'latent.host-codec.native-products.v1','status':'passed',
            'sourceRevision':revision,'source':before,'materials':inputs,'compiler':compiler,
            'products':products,'commands':stages.records,'controlCount':114,'nativeCohort':codec_wasmtime.COHORT,
            'controls':{stage:list(names) for stage,_,_,names in CONTROLS},
            'profile':'normal-managed-guest-default-features','signedQualification':False,
            'guestJavaScriptEngineCompiled':False,'guestSourceCompiled':False,
            'historicalReceiptRewritten':False,
            'scope':'ordinary-host-retained-activation-context-and-linear-allocation-notifications-codec-table-and-selected-Store-instance-buffer-registry-FuncRefs-container-resource-substitutions-original-memory-and-selected-c-public-async-type-sync-core-admission-and-authenticated-c-ready-handoff-and-closed-guest-trap-diagnostics-and-exact-native-thread-audit-codec; direct-Core-HostFunc-construction, shared-preparation-closures, concurrent-task, hostcall, request ingress and discarded scaffolding and later hostcall copies, legacy framing and serialized controller frames excluded'}
        write_json(output/'native-products.json',record)
        return record
    except Exception as error:
        write_json(output/'failure.json',{'schemaVersion':'latent.host-codec.failure.v1','status':'failed',
            'sourceRevision':revision,'errorType':type(error).__name__,
            'currentStage':stages.current,'commands':stages.records})
        raise

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--source-commit', required=True)
    args = parser.parse_args()
    print(json.dumps(qualify(args.output.resolve(),args.source_commit),sort_keys=True))
if __name__ == '__main__':
    main()
