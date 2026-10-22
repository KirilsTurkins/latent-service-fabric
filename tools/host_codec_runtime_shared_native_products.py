"""One immutable reviewed runtime strong/weak native origin; no guest qualification."""
from pathlib import Path
import hashlib
import sys

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.host_codec_native_products_reader import FrozenHostCodecProducts, _producer_contract
from tools.host_codec_owned_reply_native_products_reader import CLI_CONTROL
from tools.phase2_operator_process import require

SOURCE = '597ef2bc0db168d4aee1c2416c38f9a8b9fef9e8'
RUN = 39835325986
JOB = 120022000948
BRANCH = 'feat/runtime-shared-memory-20261022'
# Actual completed-success origin, verified from its sole bounded cache.
ARTIFACT = {'id': 12451317202, 'size_in_bytes': 70484445,
    'digest': 'sha256:1e0ddcde71403af345a266435e260b0b833e8d84aea93eefefb35f37b1432359'}
RECEIPTS = {
    'native-products.json': {'bytes': 109053,
        'sha256': 'sha256:57f6fe2ddf1e7add171f201157f82f83e3ae16e19e80ee02e5a4f8394db63080'},
    'source-inputs.json': {'bytes': 24574,
        'sha256': 'sha256:8dcbfeaf1e2e5c2f8f43fbf33efaee0be78e15cd13926b1ce8a711b0e5a357e7'},
}
PRODUCER_SHA256 = '1763edab12230491f624dfc681cb4c08b91b46f5c370821360e8173fe6fdcd85'
ALLOCATION_COHORT = 'wasmtime-48.0.7-latent-value-table-store-registry-funcrefs-resource-types-linear-notification-retained-context-host-future-owned-reply-memory-v9'
COHORT = 'wasmtime-48.0.7-latent-value-table-store-registry-funcrefs-resource-types-linear-notification-retained-context-host-future-owned-reply-retained-capability-directories-blob-streaming-shared-tables-runtime-timer-strong-weak-memory-v12'
SCOPE = 'ordinary-runtime-and-timer-strong-and-weak-Arc-backing-including-private-billing-Arc-and-ordinary-host-blob-fixed-Vec-and-streaming-HTTP-fixed-Vec-and-two-private-Shared-Arc-storage-shapes-and-three-retained-capability-directory-backings-and-six-closed-context-reply-buffers-and-concrete-callback-future-box-and-retained-activation-context-and-linear-allocation-notifications-codec-table-and-selected-Store-instance-buffer-registry-FuncRefs-container-resource-substitutions-original-memory-and-selected-c-public-async-type-sync-core-admission-and-authenticated-c-ready-handoff-and-closed-guest-trap-diagnostics-and-exact-native-thread-audit-codec-and-CLI-projection; direct-Core-HostFunc-construction, shared-preparation-closures, concurrent-task, other-hostcall-values-custom-Lower-shared-interior-error-owned-copies-and-opaque-accessor-scheduler-frames, request ingress and discarded scaffolding and other hostcall copies, SessionCore and transitive provider graphs, legacy framing and serialized controller frames excluded'
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
 'actual-runtime-timer-strong-weak-owner-run')


class _FrozenRuntimeSharedProducts(FrozenHostCodecProducts):
    cohort, scope = COHORT, SCOPE
    control_count, command_count = 163, 69
    job_name = 'Original ledger shared tables and runtime memory ownership diagnostics'

    def __init__(self):
        require(type(ARTIFACT) is dict and type(RECEIPTS) is dict,
            'runtime-shared-native-actual-success-pins-required')
        super().__init__(source=SOURCE, run=RUN, job=JOB, artifact=ARTIFACT,
            receipts=RECEIPTS, branch=BRANCH)

    def _valid_stages(self, stages):
        return stages == STAGES

    def _producer_contract(self, raw):
        require(type(raw) is bytes and hashlib.sha256(raw).hexdigest() == PRODUCER_SHA256,
            'runtime-shared-native-exact-frozen-producer')
        return _producer_contract(raw, 33, 163, extra_control=CLI_CONTROL)

    def validate_record(self, record, snapshot, native, materials):
        require(type(record) is dict and record.get('wasmtimeAllocationCohort') == ALLOCATION_COHORT,
            'runtime-shared-native-unchanged-wasmtime-allocation-cohort')
        original_schema = dict(record)
        del original_schema['wasmtimeAllocationCohort']
        super().validate_record(original_schema, snapshot, native, materials)


READER = _FrozenRuntimeSharedProducts()
prepare = READER.prepare
verify_prepared = READER.verify_prepared
native_products = READER.native_products

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    prepare(parser.parse_args().output)
