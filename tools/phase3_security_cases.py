"""Reviewed exact selections, not substring filters or a vendor certification list.

pr cases also run manually; ignored cases run explicitly only in the manual
profile after their prerequisites exist. Unselected tests are not claimed.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Case:
    name: str
    pr: bool
    ignored: bool


@dataclass(frozen=True)
class Group:
    key: str
    manifest: str
    target: str
    kind: str
    source: str
    layer: str
    issues: tuple[int, ...]
    cases: tuple[Case, ...]
    timeout: int = 90
    marker: str | None = None


def selection(rows: str, prefix: str = "") -> tuple[Case, ...]:
    result = []
    for row in rows.splitlines():
        if not row.strip():
            continue
        mode, name = row.split()
        if mode not in ("pr", "manual", "ignored"):
            raise ValueError("security-case-mode")
        result.append(Case(prefix + name, mode == "pr", mode == "ignored"))
    return tuple(result)


def guest(target: str, issues: tuple[int, ...], rows: str) -> Group:
    layer = {"isolated_aot": "real-isolated-compiler",
             "native_aot_cache": "real-native-loader-and-guest"}.get(target, "executed-guest-and-provider")
    return Group("guest-" + target, "crates/latent-wasmtime/Cargo.toml", target,
                 "test", "tests/" + target + ".rs", layer, issues, selection(rows))


def library(key: str, package: str, target: str, layer: str, issues: tuple[int, ...],
            prefix: str, rows: str) -> Group:
    return Group(key, package + "/Cargo.toml", target, "lib",
                 "src/lib_root.rs" if target == "latentd" else "src/lib.rs",
                 layer, issues, selection(rows, prefix))


GROUPS = (
    library("fixture-operator", "crates/latent-policy", "latent_policy", "fixture-export", (280,),
            "supply_chain::tests::support::operator_fixture::", """
ignored export_operator_workflow_fixture
"""),
    library("fixture-publication", "crates/latent-policy", "latent_policy", "fixture-export", (267,),
            "supply_chain::tests::support::operator_fixture::", """
ignored export_publication_workflow_fixture
"""),
    Group("fixture-provider", "apps/latentd/Cargo.toml", "phase3_workflow_fixture", "test",
          "tests/phase3_workflow_fixture.rs", "fixture-export", (226,), selection("""
ignored export_signed_provider_workflow_fixtures
""")),
    Group("fixture-angular", "apps/latentd/Cargo.toml", "phase3_angular_fixture", "test",
          "tests/phase3_angular_fixture.rs", "actual-build-fixture-export", (226, 238), selection("""
ignored export_actual_angular_t1_fixtures
""")),
    guest("broker", (204, 205, 238, 272), """
pr real_guest_calls_use_fresh_sessions_on_the_same_warm_cell
manual real_guest_runs_with_the_original_phase3_ledger_and_unused_counters_stay_zero
pr revocation_during_first_real_host_call_denies_the_second_call_without_deadlocking
pr runtime_rejects_forged_owner_context_before_store_or_provider_creation
manual cancellation_in_a_provider_prevents_the_next_guest_call_and_reclaims_owners
manual managed_factories_and_shutdown_enforce_catalog_and_policy_owners
pr async_io::canonical_async_guest_retains_store_and_cell_cleanup_until_consumer_retires
manual async_io::canonical_async_cancellation_and_shutdown_stop_delivery_and_acknowledge_cleanup
manual async_io::completed_async_consumers_allow_reuse_and_unpolled_guests_start_no_io
"""),
    guest("http", (211, 238, 271), """
pr real_guest_executes_every_method_and_reclaims_the_same_warm_cell
pr guest_denial_and_trap_preserve_transport_and_store_cleanup
pr guest_cancellation_closes_inflight_io_and_reclaims_store
manual revoked_policy_and_missing_provider_cannot_use_prepared_http_imports
"""),
    guest("streaming_http", (212, 238, 271), """
manual guest_reads_before_full_body_and_store_drop_closes_the_stream
manual resource_guest_drains_chunks_and_trailers_then_reclaims_all_owners
pr traps_wrong_kind_stale_handles_and_abort_close_real_owners
manual abort_or_trap_before_upload_finishes_reclaims_the_connection
pr cancellation_of_a_suspended_guest_read_closes_socket_and_all_resources
manual a_revoked_grant_blocks_a_new_stream_before_any_network_work
manual no_streaming_provider_means_no_prepared_stream_import
manual dormant_streaming_deployments_create_no_provider_or_activation_owners
"""),
    guest("local_blobs", (213, 238), """
manual guest_writes_seals_and_reads_exact_bounded_chunks
pr guest_handle_abandonment_wrong_kind_and_trap_reclaim_actual_owners
pr a_previous_activation_numeric_handle_cannot_be_reused
manual dormant_blob_deployments_allocate_no_store_provider_work_or_file_handles
manual provider::retained_writer_rechecks_revocation_before_physical_write
manual provider::chunks_and_file_handles_keep_independent_ownership_until_real_drop
manual provider::closed_session_cannot_reauthorize_retained_writer
manual provider::cumulative_byte_budgets_reject_before_further_physical_io
"""),
    guest("local_secrets", (215, 238), """
pr guest_read_version_errors_rotation_and_cell_reuse
pr held_read_is_rejected_after_rotation_and_keeps_old_generation_charged
manual failed_reload_preserves_generation_and_current_guest_value
manual cancellation_stale_sessions_revocation_and_traps_release_reads
manual expiry_is_checked_at_disclosure_and_cannot_be_undone_by_clock_rollback
manual dormant_deployments_acquire_no_secret_owner_or_provider_work
manual audit::real_secret_audit_and_status_contain_no_plaintext_or_value_digest
manual ownership::a_queued_read_selects_current_material_and_rechecks_revocation
manual ownership::actual_guest_waiting_for_a_read_rejects_rotation_and_cancellation
manual ownership::abandoned_reload_does_not_refund_or_commit_its_still_running_worker
manual ownership::closing_the_store_fences_retained_reads_and_a_candidate_worker
manual tls_credentials::protocol_purpose_and_destination_cannot_be_substituted_or_retained_after_rotation
"""),
    guest("nats_events", (217, 238, 271), """
pr bounds::malformed_foreign_oversized_and_unavailable_receipts_keep_explicit_semantics
manual bounds::malformed_inputs_are_rejected_before_network_or_budget_dispatch
manual bounds::original_timeout_covers_multiple_protocol_waits_before_publication
manual bounds::queued_cancellation_and_dropped_publish_keep_physical_owners_bounded
"""),
    guest("local_service", (208, 209, 238, 272), """
manual two_real_components_use_compiled_binding_normal_admission_and_child_accounting
pr acceptance::concurrent_imports_reserve_distinct_children_and_cannot_reuse_a_spent_call_grant
manual acceptance::denied_service_publication_never_starts_a_child
manual acceptance::explicit_cross_tenant_policy_and_fresh_activation_identity
manual acceptance::declared_failure_is_distinct_from_a_platform_failure
manual acceptance::oversized_input_unknown_targets_and_expired_deadline_never_start_children
pr acceptance::parent_occupying_the_only_cell_rejects_children_promptly_and_keeps_running
pr acceptance::cancellation_during_child_execution_reclaims_both_stores_and_reservations
manual acceptance::abandoning_parent_awaiter_still_drives_child_cleanup
manual acceptance::changed_route_requires_a_new_plan_and_revocation_denies_cached_target
manual acceptance::required_audit_records_real_local_acceptance_and_denies_full_sink_before_child_admission
"""),
    guest("s3_blobs", (214, 238, 271), """
manual faults::lost_create_and_embedded_completion_error_remain_uncertain
manual faults::unverified_range_bytes_never_become_a_guest_chunk
manual faults::late_part_restart_and_unavailable_cleanup_keep_the_inventory_charged
manual faults::revocation_and_exhausted_request_budget_reject_before_s3_dispatch
"""),
    guest("vault_secrets", (216, 238), """
manual bounds::aggregate_plaintext_exhaustion_rejects_before_opening_another_connection
manual bounds::replacement_requires_a_fresh_plan_and_keeps_old_owners_until_drain
manual bounds::malformed_oversized_and_denied_responses_are_redacted_and_reclaimed
manual bounds::evicted_disclosures_keep_plaintext_charged_until_their_last_owner_drops
manual bounds::a_late_response_cannot_replace_or_disclose_an_older_latest_version
"""),
    library("http-network", "crates/latent-http", "latent_http", "real-provider-network",
            (211, 238, 271), "tests::", """
pr dns::expired_dns_cannot_reuse_an_idle_socket_after_rebinding_to_metadata
manual dns::dns_wait_cancels_and_refunds_its_actual_socket
pr redirects::redirects_reauthorize_and_strip_credentials_without_one_slot_deadlock
manual redirects::redirected_path_is_checked_and_mutations_are_not_followed
manual http::lost_mutation_reply_is_uncertain_and_never_retried
manual ownership::cancelling_a_partial_mutation_write_is_uncertain_and_closes_the_socket
manual responses::lengths_framing_and_compression_are_bounded
manual responses::a_slow_body_cannot_refresh_the_original_deadline
manual responses::trailers_and_unsolicited_response_bytes_cannot_change_the_next_result
manual secret_references::both_http_profiles_use_rotated_opaque_credentials_and_refuse_revoked_material
manual secret_references::provider_bindings_reject_wrong_tenant_origin_header_and_guest_overrides
manual validation::special_addresses_require_exact_opt_in_even_with_broad_networks
manual tls::tls_requires_both_approved_peer_and_correct_trusted_hostname
"""),
    library("registry-network", "crates/latent-oci", "latent_oci", "real-registry-network",
            (270, 238), "http::network::tests::", """
pr dns::shared_dns_cache_expires_and_rebinding_never_reaches_the_tls_peer
manual dns::cancellation_and_deadline_retire_dns_sockets_without_background_jobs
manual explicit_network_profile_uses_owned_tls_and_preserves_bearer_cache
manual literal_address_policy_and_tls_names_cannot_be_bypassed
pr redirects::approved_content_redirects_strip_credentials_and_retain_digest_validation
manual redirects::foreign_origins_paths_userinfo_downgrades_and_token_targets_are_denied
manual redirects::token_redirects_and_mutation_redirects_never_replay_or_forward_credentials
manual ownership::cancelling_owned_token_acquisition_retires_socket_before_follower_recovery
manual ownership::stalled_tls_cancellation_and_deadline_close_the_actual_socket
manual ownership::body_deadline_closes_the_physical_connection_before_refund
manual ownership::shutdown_deadline_keeps_the_retained_connection_visible_until_body_retirement
manual ownership::response_metadata_is_bounded_and_failure_retires_its_socket
manual upload::cancellation_before_upload_location_keeps_socket_bytes_and_cleanup_owned
manual upload::cancelled_upload_put_closes_its_socket_but_keeps_the_cleanup_reservation
"""),
    library("grpc-residency", "apps/latentd", "latentd", "real-shared-ingress", (238, 277),
            "standalone::transport::tests::network::", """
manual accepted_connections_are_bounded_and_incomplete_http2_is_closed_on_shutdown
pr unauthenticated_deadline_reclaims_silent_and_partial_connection_slots
manual protocol::completed_http2_without_requests_expires_while_idle
pr protocol::completed_http2_and_ping_traffic_do_not_authenticate_a_connection
manual protocol::rejected_authentication_cannot_renew_connection_residency
manual lifetime::every_rpc_authenticates_after_the_first_connection_deadline
manual lifetime::age_drain_rejects_new_calls_but_allows_an_owned_call_to_finish
manual lifetime::maximum_age_retires_stalled_rpc_and_its_owned_state
manual lifetime::peer_drop_and_node_shutdown_retire_active_connection_owners_once
"""),
    library("browser-ingress", "apps/latentd", "latentd", "real-shared-ingress", (235, 238),
            "standalone::http::", """
pr assets::browser::browser_boundary_reclaims_two_incomplete_peers_and_continues_eligible_asset_admission
manual tests::browser::browser_boundary_rejects_cross_origin_csrf_spoofing_and_tenant_aliases_before_routing
manual tests::browser::browser_boundary_framing_traversal_cookie_and_compression_abuse_is_bounded
manual tests::browser::browser_boundary_proxy_scheme_and_origin_are_fixed_not_forwarded
"""),
    library("protected-files", "crates/latent-protected-files", "latent_protected_files",
            "real-filesystem", (238, 278), "", """
manual tests::secret_policy_accepts_owner_service_group_and_private_directory_reads
manual tests::secret_policy_rejects_public_reads_on_traversable_paths_and_writable_group_access
manual tests::integrity_policy_allows_public_reads_but_not_untrusted_writes
manual tests::symlinks_hardlinks_and_untrusted_ancestor_writes_fail_closed
pr tests::pathname_replacement_does_not_redirect_opened_descriptor
manual tests::content_change_after_snapshot_fails_closed
pr tests::fifo_is_rejected_without_waiting_for_a_writer
manual tests::named_user_acl_cannot_hide_behind_a_trusted_service_group
ignored tests::unexpected_file_and_directory_owners_are_rejected
manual rooted::tests::rooted_reads_reject_unbounded_names_types_links_and_sizes
manual rooted::tests::replacement_and_removal_during_read_never_return_old_bytes
manual rooted::tests::retained_root_rejects_ancestor_replacement_and_permission_changes
manual rooted::tests::content_or_permission_change_after_open_is_rejected
"""),
    library("profile-startup", "apps/latentd", "latentd", "configuration-and-reopened-storage",
            (238, 273, 278, 280), "config::", """
pr tests::security::a_profile_label_cannot_replace_enforced_admission_or_isolated_compilation
manual tests::security::an_external_catalog_requirement_survives_reopen_and_blocks_an_omitted_profile
manual tests::security::local_check_config_reports_actual_controls_without_secrets_or_storage
manual tests::security::profile_marker_rejects_links_and_unprotected_directories_and_leaves_targets_untouched
manual tests::security::unavailable_profiles_and_a_forged_file_protection_flag_are_not_configuration
manual aot::tests::key::wrong_lengths_permissions_and_links_reject_with_static_errors
manual aot::tests::key::zero_key_and_cache_symlink_aliases_cannot_enter_settings
"""),
    library("authority-intersection", "crates/latent-capabilities", "latent_capabilities",
            "supporting-broker-authority", (204, 238), "broker::tests::", """
manual import_operation_resource_and_principal_cannot_be_widened_by_descriptive_data
manual foreign_catalog_plan_tenant_publication_and_ledger_shapes_fail_closed
manual unpolled_calls_reserve_nothing_and_revocation_denies_before_dispatch
manual accepted_provider_runs_without_authority_locks_and_may_finish_after_policy_revocation
manual actual_provider_budget_charges_are_atomic_required_and_committed_before_dispatch
manual provider_errors_unwind_and_foreign_responses_cannot_leak_work_or_identity
"""),
    library("blob-storage", "crates/latent-blobs", "latent_blobs", "real-filesystem-provider",
            (213, 238, 271), "local::tests::", """
manual duplicate_publication_and_tenant_authority_are_independent
manual pinned_released_object_is_not_reclaimed_and_drop_does_no_deletion
manual security::insecure_roots_and_symlink_ancestors_are_rejected
manual security::corrupted_or_missing_payload_never_becomes_a_successful_read
manual security::replacement_cannot_redirect_an_open_reader_or_reclamation
manual failures::uncertain_publication_recovers_the_physical_inventory_without_refund
manual failures::failed_unlink_or_sync_does_not_refund_and_reopens_as_unreferenced
manual failures::cancellation_and_shutdown_keep_running_file_work_until_the_worker_retires
"""),
    library("parent-package-parsers", "crates/latent-packaging", "latent_packaging",
            "supporting-parent-parser", (238, 273, 279), "", """
manual semantics::lexical::tests::lexical_bounds_precede_recursive_source_parsing
manual semantics::metadata::tests::package_docs_are_bounded_before_upstream_serde_allocation
manual semantics::projection::tests::parameter_result_and_async_metadata_cannot_lie_after_rehashing
manual sbom::tests::duplicate_identity_and_conflicting_context_attribution_fail
manual sbom::tests::normalized_input_and_json_are_bounded_before_typed_materialization
manual sbom::tests::package_input_bounds_precede_inventory_work
"""),
    library("parent-catalog-evidence", "crates/latent-artifacts", "latent_artifacts",
            "real-catalog-and-parent-parser", (238, 267, 273, 279), "local_repository::", """
manual contract_metadata::tests::unknown_versions_fields_and_duplicate_keys_are_rejected_without_raw_diagnostics
manual tests::verified_metadata::streamed_metadata_rejects_malformed_metadata_even_with_matching_completion_hash
manual tests::oversized_persisted_metadata_is_rejected_before_allocation_on_reopen
manual tests::admission::corrupt_evidence_is_not_classified_as_expired_history
manual tests::admission::new_package_coexists_but_cannot_replace_an_existing_packages_evidence
manual tests::publications::same_component_metadata_revisions_keep_independent_authority_and_legacy_replay
manual tests::integrity::recovery::legacy_and_mixed_catalogs_are_rejected_without_rewriting_committed_bytes
"""),
    library("evidence-authority", "crates/latent-policy", "latent_policy",
            "real-catalog-trust-authority", (238, 267, 273, 280), "supply_chain::tests::", """
manual catalog::malformed_or_missing_evidence_never_creates_preparation_authority
manual authority::required_evidence_tamper_wrong_tenant_and_spare_capacity_reject
manual authority::policy_change_revokes_old_grants_and_exact_original_evidence_can_refresh
manual lifecycle::bad_evidence_wrong_package_and_new_policy_denial_cannot_advance_lifecycle
"""),
    guest("isolated_aot", (238, 273, 279, 280), """
manual ownership::real_compile_binds_exact_source_and_keeps_output_capacity_until_drop
manual ownership::cancelled_unstarted_job_retains_its_reservation_until_consumed
manual ownership::queued_deadline_is_not_restarted_when_the_job_runs
manual ownership::shutdown_does_not_refund_a_held_job_and_closes_admission
manual source::tampered_component_is_rejected_by_the_fresh_catalog_read
manual source::queued_job_cannot_upgrade_its_revoked_lifecycle_capability
manual source::over_budget_and_noncanonical_sources_fail_before_fresh_io
manual source::compiler_binary_digest_and_actual_engine_profile_are_checked
manual source::invalid_portable_bytes_fail_in_the_child_without_a_trusted_output
"""),
    guest("native_aot_cache", (238, 267, 279, 280), """
manual reopen::identical_component_after_restart_requires_its_exact_engine_before_native_reuse
manual reopen::real_miss_invokes_then_reopened_native_hit_verifies_source_without_compiling
manual tamper::replaced_bytes_with_matching_sha_and_wrong_host_key_never_reach_the_loader
manual ownership::evicted_ready_handle_keeps_its_image_and_revocation_never_recovers_from_native_cache
"""),
    library("current-trust", "apps/latentd", "latentd", "real-native-node-currentness",
            (238, 267, 273, 280), "standalone::start::tests::trust_currentness::", """
ignored profile::external_profile_preserves_cold_warm_and_restart_requirements
ignored real_policy_expiry_denies_native_work_and_recovers_readable_negative_history
ignored real_proof_age_expiry_denies_retained_native_work_with_a_current_clock_lease
ignored real_publisher_revocation_denies_native_work_without_any_registry_event
"""),
    library("web-component", "apps/latentd", "latentd", "real-web-component-and-ingress",
            (235, 238), "standalone::http::tests::", """
ignored browser_component::actual_http_component_browser_policy_rejects_unsafe_output_without_reflecting_identity
ignored cache::actual_http_component_cache_preserves_admission_revocation_and_owner_reclamation
ignored lifecycle::actual_http_component_public_origin_deadline_and_forced_shutdown_reclaim_owners
ignored real::actual_http_component_authenticates_executes_cancels_and_recovers
ignored real_delivery::actual_http_component_tls_body_and_slow_output_keep_owners_until_retirement
ignored real_delivery::actual_http_component_pinned_cutover_and_revocation_use_current_authority
"""),
    library("actual-browser", "apps/latentd", "latentd", "node-ssr-and-real-browser-not-t1-wasm",
            (235, 238), "standalone::http::assets::browser::", """
ignored actual_browser_boundary_hydrates_navigates_and_blocks_injection_on_live_ingress
"""),
    library("actual-browser-application", "apps/latentd", "latentd", "real-browser-and-public-component",
            (235, 238), "standalone::http::assets::browser::", """
ignored actual_browser_application_uses_only_the_public_shared_http_contract
"""),
    guest("guest_sdk", (217, 238, 271), """
ignored events::typed_event_receipt_denial_and_uncertainty_do_not_retry
"""),
    Group("compiler-supervisor", "crates/latent-wasmtime/Cargo.toml", "aot_supervisor", "test",
          "tests/aot_supervisor.rs", "real-child-supervisor-not-production-sandbox", (238, 280),
          (), 180, "isolated AOT readiness: six bounded success/rejection/reap scenarios passed\n"
          "isolated AOT supervisor: 16 bounded protocol/ownership scenarios passed"),
    Group("compiler-sandbox", "crates/latent-wasmtime/Cargo.toml", "aot_sandbox", "test",
          "tests/aot_sandbox.rs", "production-compiler-sandbox-not-guest-process", (238, 273, 280),
          (), 90, "AOT sandbox: 12 unprivileged real-entry probes and exact-policy syscall probe passed"),
)


def selected(profile: str) -> tuple[Group, ...]:
    if profile == "manual":
        return GROUPS
    if profile != "pr":
        raise ValueError("security-profile")
    return tuple(group for group in GROUPS if any(case.pr for case in group.cases))
