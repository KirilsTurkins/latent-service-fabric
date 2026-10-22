"""One immutable reviewed native-only cumulative retirement native origin; no guest qualification."""
from pathlib import Path
import hashlib
import sys

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.host_codec_native_products_reader import FrozenHostCodecProducts, _producer_contract
from tools.host_codec_owned_reply_native_products_reader import CLI_CONTROL
from tools.phase2_operator_process import require

SOURCE = 'b606b1402961593dd918722a66fe293bfab9b319'
RUN = 39869241256
JOB = 120139175577
BRANCH = 'feat/session-core-memory-20261022'
# Actual completed-success origin, verified from its sole bounded cache.
ARTIFACT = {'digest': 'sha256:d877dbebf42935a137ebcf966406bee6ebe93946ca79a9a78c696a0dacd97a7e',
 'id': 12466206919,
 'size_in_bytes': 70510666}
RECEIPTS = {'native-products.json': {'bytes': 119004,
                          'sha256': 'sha256:4f55d3c5e458849ec01f6ff6304f425b4b9126bd831e35a561ab8b84b0752f22'},
 'source-inputs.json': {'bytes': 24574,
                        'sha256': 'sha256:2a54d15feca9f5aaa884475d1cf5a6f8c45761bf40f4dd37935aa4d16004c39d'}}
PRODUCER_SHA256 = 'd8785f96739e04f28dabec3e10540543ae8ca3252f35aa5f10953da0380d2768'
ALLOCATION_COHORT = 'wasmtime-48.0.7-latent-value-table-store-registry-funcrefs-resource-types-linear-notification-retained-context-host-future-owned-reply-memory-v9'
COHORT = 'wasmtime-48.0.7-latent-value-table-store-registry-funcrefs-resource-types-linear-notification-retained-context-host-future-owned-reply-retained-capability-directories-blob-streaming-shared-tables-runtime-timer-strong-weak-session-core-stats-c-canonical-system-stack-native-only-cumulative-retirement-memory-v14'
SCOPE = 'ordinary-physical-native-only-accounting-retention-separate-from-last-ordinary-owner-cumulative-child-retirement-and-original-sealed-session-Core-and-Stats-strong-and-weak-Arc-backing-including-both-private-billing-Arcs-owned-identity-text-and-fixed-handle-slots-and-selected-C-canonical-realloc-private-System-stack-routing-and-ordinary-runtime-and-timer-strong-and-weak-Arc-backing-including-private-billing-Arc-and-ordinary-host-blob-fixed-Vec-and-streaming-HTTP-fixed-Vec-and-two-private-Shared-Arc-storage-shapes-and-three-retained-capability-directory-backings-and-six-closed-context-reply-buffers-and-concrete-callback-future-box-and-retained-activation-context-and-linear-allocation-notifications-codec-table-and-selected-Store-instance-buffer-registry-FuncRefs-container-resource-substitutions-original-memory-and-selected-c-public-async-type-sync-core-admission-and-authenticated-c-ready-handoff-and-closed-guest-trap-diagnostics-and-exact-native-thread-audit-codec-and-CLI-projection; direct-Core-HostFunc-construction, shared-preparation-closures, concurrent-task, other-hostcall-values-custom-Lower-shared-interior-error-owned-copies-and-opaque-accessor-scheduler-frames, request ingress and discarded scaffolding and other hostcall copies, shared broker and compiled-plan preparation, HandleEntry and transitive provider payload/transport/queue graphs, legacy framing and serialized controller frames excluded'
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
 'actual-native-only-cumulative-retirement-run')


class _FrozenRetirementNativeProducts(FrozenHostCodecProducts):
    cohort, scope = COHORT, SCOPE
    control_count, command_count = 177, 77
    job_name = 'Original ledger shared tables and runtime memory ownership diagnostics'

    def __init__(self):
        require(type(ARTIFACT) is dict and type(RECEIPTS) is dict,
            'retirement-native-actual-success-pins-required')
        super().__init__(source=SOURCE, run=RUN, job=JOB, artifact=ARTIFACT,
            receipts=RECEIPTS, branch=BRANCH)

    def _valid_stages(self, stages):
        return stages == STAGES

    def _producer_contract(self, raw):
        require(type(raw) is bytes and hashlib.sha256(raw).hexdigest() == PRODUCER_SHA256,
            'retirement-native-exact-frozen-producer')
        return _producer_contract(raw, 37, 177, extra_control=CLI_CONTROL)

    def validate_record(self, record, snapshot, native, materials):
        require(type(record) is dict and record.get('wasmtimeAllocationCohort') == ALLOCATION_COHORT,
            'retirement-native-unchanged-wasmtime-allocation-cohort')
        original_schema = dict(record)
        del original_schema['wasmtimeAllocationCohort']
        super().validate_record(original_schema, snapshot, native, materials)


READER = _FrozenRetirementNativeProducts()
prepare = READER.prepare
verify_prepared = READER.verify_prepared
native_products = READER.native_products

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    prepare(parser.parse_args().output)
