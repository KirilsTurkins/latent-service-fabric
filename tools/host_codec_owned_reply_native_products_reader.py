"""Closed v9 owned-reply/CLI projection schema; no acquisition tuple here."""
from tools.host_codec_native_products_reader import FrozenHostCodecProducts, _producer_contract
from tools.phase2_operator_process import require

COHORT = 'wasmtime-48.0.7-latent-value-table-store-registry-funcrefs-resource-types-linear-notification-retained-context-host-future-owned-reply-memory-v9'
SCOPE = 'ordinary-host-six-closed-context-reply-buffers-and-concrete-callback-future-box-and-retained-activation-context-and-linear-allocation-notifications-codec-table-and-selected-Store-instance-buffer-registry-FuncRefs-container-resource-substitutions-original-memory-and-selected-c-public-async-type-sync-core-admission-and-authenticated-c-ready-handoff-and-closed-guest-trap-diagnostics-and-exact-native-thread-audit-codec-and-CLI-projection; direct-Core-HostFunc-construction, shared-preparation-closures, concurrent-task, other-hostcall-values-custom-Lower-shared-interior-error-owned-copies-and-opaque-accessor-scheduler-frames, request ingress and discarded scaffolding and other hostcall copies, legacy framing and serialized controller frames excluded'
CLI_CONTROL = ('cli-native-thread-audit-projection', 'latent', 'native_thread_audit_projection_', (
    'management::phase2::projection::audit::capability::tests::native_thread_audit_projection_preserves_exact_v6_facts_without_default_authority',
    'management::phase2::projection::audit::capability::tests::native_thread_audit_projection_refuses_foreign_versions_classes_operations_and_outcomes'))


def producer_contract(raw):
    controls, recipe = _producer_contract(raw, 28, 128, extra_control=CLI_CONTROL)
    require(controls[-1] == CLI_CONTROL, 'codec-reader-exact-closed-cli-projection-group')
    return controls, recipe


class FrozenHostCodecOwnedReplyProducts(FrozenHostCodecProducts):
    cohort, scope = COHORT, SCOPE
    control_count, command_count = 128, 59
    job_name = 'Original ledger closed context replies and runtime memory ownership diagnostics'

    def _producer_contract(self, raw):
        return producer_contract(raw)
