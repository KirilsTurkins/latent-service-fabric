"""One immutable 188-control handle and copied-buffer native origin; no guest qualification."""
from pathlib import Path
import hashlib
import sys

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.host_codec_native_products_reader import FrozenHostCodecProducts, _producer_contract
from tools.host_codec_owned_reply_native_products_reader import CLI_CONTROL
from tools.phase2_operator_process import require

SOURCE = 'c802283a5546620f071bd02ec01c410696893c5b'
RUN = 39878219065
JOB = 120168986663
BRANCH = 'feat/handle-entry-current-20261023'
# Actual completed-success origin, verified from its sole bounded cache.
ARTIFACT = {'id': 12469896595, 'size_in_bytes': 70542067, 'digest': 'sha256:5f19c381de636fa22a7a5aa529f3da8ba574eea8fcd0b1cb1e6e895ed6e2c52f'}
RECEIPTS = {'native-products.json': {'bytes': 128565, 'sha256': 'sha256:7930e19a6a61f15ebff9409337885c92b7de5c706eed9b6deea58a176752efeb'}, 'source-inputs.json': {'bytes': 24881, 'sha256': 'sha256:fc56f740d5110eb945864e9c696e7350b9e58b8b2c7f3ed2ae32f3d486fc5f3b'}}
PRODUCER_SHA256 = '684733c172dd6daf12b611cf80f74564054bf95bc74312f70eedfe4013c58375'
ALLOCATION_COHORT = 'wasmtime-48.0.7-latent-value-table-store-registry-funcrefs-resource-types-linear-notification-retained-context-host-future-owned-reply-memory-v9'
COHORT = 'wasmtime-48.0.7-latent-value-table-store-registry-funcrefs-resource-types-linear-notification-retained-context-host-future-owned-reply-retained-capability-directories-blob-streaming-shared-tables-runtime-timer-strong-weak-session-core-stats-c-canonical-system-stack-native-only-cumulative-retirement-physical-result-owner-box-handle-owned-text-call-buffers-memory-v15'
SCOPE = 'original-copied-Work-input-and-OwnedCapabilityResponse-byte-buffers-and-original-HandleEntry-row-and-every-owned-resource-text-copy-and-pending-clock-row-followed-by-ordinary-physical-native-only-accounting-retention-separate-from-last-ordinary-owner-cumulative-child-retirement-and-original-sealed-session-Core-and-Stats-strong-and-weak-Arc-backing-including-both-private-billing-Arcs-owned-identity-text-and-fixed-handle-slots-and-selected-C-canonical-realloc-private-System-stack-routing-and-ordinary-runtime-and-timer-strong-and-weak-Arc-backing-including-private-billing-Arc-and-ordinary-host-blob-fixed-Vec-and-streaming-HTTP-fixed-Vec-and-two-private-Shared-Arc-storage-shapes-and-three-retained-capability-directory-backings-and-six-closed-context-reply-buffers-and-concrete-callback-future-box-and-retained-activation-context-and-linear-allocation-notifications-codec-table-and-selected-Store-instance-buffer-registry-FuncRefs-container-resource-substitutions-original-memory-and-selected-c-public-async-type-sync-core-admission-and-authenticated-c-ready-handoff-and-closed-guest-trap-diagnostics-and-exact-native-thread-audit-codec-and-CLI-projection; direct-Core-HostFunc-construction, shared-preparation-closures, concurrent-task, other-hostcall-values-custom-Lower-shared-interior-error-owned-copies-and-opaque-accessor-scheduler-frames, request ingress and discarded scaffolding and other hostcall copies, shared broker and compiled-plan preparation and transitive provider payload/transport/queue graphs, legacy framing and serialized controller frames excluded'
STAGES = ('source-revision',
 'rust-version',
 'normal-host-build',
 'original-host-memory-list',
 'original-host-memory-run',
 'result-owner-list',
 'result-owner-run',
 'result-wire-list',
 'result-wire-run',
 'result-capacity-list',
 'result-capacity-run',
 'actual-host-codec-list',
 'actual-host-codec-run',
 'actual-dynamic-allocation-hook-list',
 'actual-dynamic-allocation-hook-run',
 'raw-input-lifetime-list',
 'raw-input-lifetime-run',
 'result-lifetime-list',
 'result-lifetime-run',
 'original-accounting-list',
 'original-accounting-run',
 'child-capacity-list',
 'child-capacity-run',
 'c-public-async-type-list',
 'c-public-async-type-run',
 'c-public-sync-abi-list',
 'c-public-sync-abi-run',
 'journal-result-retirement-list',
 'journal-result-retirement-run',
 'ordinary-backend-list',
 'ordinary-backend-run',
 'actual-native-table-owner-list',
 'actual-native-table-owner-run',
 'actual-native-store-owner-list',
 'actual-native-store-owner-run',
 'closed-guest-trap-diagnostics-list',
 'closed-guest-trap-diagnostics-run',
 'actual-native-registry-owner-list',
 'actual-native-registry-owner-run',
 'actual-native-funcrefs-owner-list',
 'actual-native-funcrefs-owner-run',
 'c-ready-handoff-list',
 'c-ready-handoff-run',
 'resource-substitutions-list',
 'resource-substitutions-run',
 'actual-linear-allocation-notifications-list',
 'actual-linear-allocation-notifications-run',
 'native-thread-audit-codec-list',
 'native-thread-audit-codec-run',
 'retained-activation-context-list',
 'retained-activation-context-run',
 'actual-host-future-owner-list',
 'actual-host-future-owner-run',
 'c-canonical-wait-routes-list',
 'c-canonical-wait-routes-run',
 'actual-owned-context-reply-list',
 'actual-owned-context-reply-run',
 'cli-native-thread-audit-projection-list',
 'cli-native-thread-audit-projection-run',
 'actual-retained-capability-directory-list',
 'actual-retained-capability-directory-run',
 'actual-streaming-table-shared-owner-list',
 'actual-streaming-table-shared-owner-run',
 'actual-blob-table-owner-list',
 'actual-blob-table-owner-run',
 'original-session-table-native-owner-list',
 'original-session-table-native-owner-run',
 'actual-runtime-timer-strong-weak-owner-list',
 'actual-runtime-timer-strong-weak-owner-run',
 'original-session-native-owner-list',
 'original-session-native-owner-run',
 'original-session-optional-shared-owner-list',
 'original-session-optional-shared-owner-run',
 'c-canonical-private-system-stack-list',
 'c-canonical-private-system-stack-run',
 'actual-native-only-cumulative-retirement-list',
 'actual-native-only-cumulative-retirement-run',
 'original-handle-owned-text-list',
 'original-handle-owned-text-run',
 'original-handle-native-owner-list',
 'original-handle-native-owner-run',
 'original-pending-clock-handle-native-owner-list',
 'original-pending-clock-handle-native-owner-run',
 'original-call-native-buffer-owner-list',
 'original-call-native-buffer-owner-run')


class _FrozenHandleBufferNativeProducts(FrozenHostCodecProducts):
    cohort, scope = COHORT, SCOPE
    control_count, command_count = 188, 85
    job_name = 'Original ledger shared tables and runtime memory ownership diagnostics'

    def __init__(self):
        require(type(ARTIFACT) is dict and type(RECEIPTS) is dict,
            'handle-buffer-native-actual-success-pins-required')
        super().__init__(source=SOURCE, run=RUN, job=JOB, artifact=ARTIFACT,
            receipts=RECEIPTS, branch=BRANCH, event='workflow_dispatch')

    def _valid_stages(self, stages):
        return stages == STAGES

    def _producer_contract(self, raw):
        require(type(raw) is bytes and hashlib.sha256(raw).hexdigest() == PRODUCER_SHA256,
            'handle-buffer-native-exact-frozen-producer')
        return _producer_contract(raw, 41, 188, extra_control=CLI_CONTROL, recipe_count=24)

    def validate_record(self, record, snapshot, native, materials):
        require(type(record) is dict and record.get('wasmtimeAllocationCohort') == ALLOCATION_COHORT,
            'handle-buffer-native-unchanged-wasmtime-allocation-cohort')
        original_schema = dict(record)
        del original_schema['wasmtimeAllocationCohort']
        super().validate_record(original_schema, snapshot, native, materials)


READER = _FrozenHandleBufferNativeProducts()
prepare = READER.prepare
verify_prepared = READER.verify_prepared
native_products = READER.native_products

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    prepare(parser.parse_args().output)
