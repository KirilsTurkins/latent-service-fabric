"""One immutable reviewed shared-table native origin; no guest qualification."""
from pathlib import Path
import hashlib
import sys

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.host_codec_native_products_reader import FrozenHostCodecProducts, _producer_contract
from tools.host_codec_owned_reply_native_products_reader import CLI_CONTROL
from tools.phase2_operator_process import require

SOURCE = '1d5062ee63c0d5ff202d47e21793f6fb9bb8a21a'
RUN = 39826486316
JOB = 119991014294
BRANCH = 'feat/streaming-table-memory-20261022'
ARTIFACT = {'id': 12447931391, 'size_in_bytes': 70484951,
    'digest': 'sha256:5cc8fbec9ce4113c0dddd2800449a9cc282592a2ccaef5588e65ae4087e4db41'}
RECEIPTS = {
    'native-products.json': {'bytes': 105178,
        'sha256': 'sha256:092538e044e5cdb742f775223eb250222d030916b8ea3fb2f78b7aa6eba0e4aa'},
    'source-inputs.json': {'bytes': 24574,
        'sha256': 'sha256:1d8b20c0c21fbf6345946abc9052e978fd33acd20418db40b5a8ba127ef0ce2d'},
}
PRODUCER_SHA256 = '2ce6ff728beb1fe2f9ada36f4e5edb92acc38616a2a06e52b7cf10fa386a9107'
ALLOCATION_COHORT = 'wasmtime-48.0.7-latent-value-table-store-registry-funcrefs-resource-types-linear-notification-retained-context-host-future-owned-reply-memory-v9'
COHORT = 'wasmtime-48.0.7-latent-value-table-store-registry-funcrefs-resource-types-linear-notification-retained-context-host-future-owned-reply-retained-capability-directories-blob-streaming-shared-tables-memory-v11'
SCOPE = 'ordinary-host-blob-fixed-Vec-and-streaming-HTTP-fixed-Vec-and-two-private-Shared-Arc-storage-shapes-and-three-retained-capability-directory-backings-and-six-closed-context-reply-buffers-and-concrete-callback-future-box-and-retained-activation-context-and-linear-allocation-notifications-codec-table-and-selected-Store-instance-buffer-registry-FuncRefs-container-resource-substitutions-original-memory-and-selected-c-public-async-type-sync-core-admission-and-authenticated-c-ready-handoff-and-closed-guest-trap-diagnostics-and-exact-native-thread-audit-codec-and-CLI-projection; direct-Core-HostFunc-construction, shared-preparation-closures, concurrent-task, other-hostcall-values-custom-Lower-shared-interior-error-owned-copies-and-opaque-accessor-scheduler-frames, request ingress and discarded scaffolding and other hostcall copies, SessionCore and transitive provider graphs, legacy framing and serialized controller frames excluded'
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
 'original-session-table-native-owner-run')


class _FrozenSharedTableProducts(FrozenHostCodecProducts):
    cohort, scope = COHORT, SCOPE
    control_count, command_count = 146, 67
    job_name = 'Original ledger shared tables and runtime memory ownership diagnostics'

    def __init__(self):
        require(type(ARTIFACT) is dict and type(RECEIPTS) is dict,
            'shared-table-native-actual-success-pins-required')
        super().__init__(source=SOURCE, run=RUN, job=JOB, artifact=ARTIFACT,
            receipts=RECEIPTS, branch=BRANCH)

    def _valid_stages(self, stages):
        return stages == STAGES

    def _producer_contract(self, raw):
        require(type(raw) is bytes and hashlib.sha256(raw).hexdigest() == PRODUCER_SHA256,
            'shared-table-native-exact-frozen-producer')
        return _producer_contract(raw, 32, 146, extra_control=CLI_CONTROL)

    def validate_record(self, record, snapshot, native, materials):
        require(type(record) is dict and record.get('wasmtimeAllocationCohort') == ALLOCATION_COHORT,
            'shared-table-native-unchanged-wasmtime-allocation-cohort')
        original_schema = dict(record)
        del original_schema['wasmtimeAllocationCohort']
        super().validate_record(original_schema, snapshot, native, materials)


READER = _FrozenSharedTableProducts()
prepare = READER.prepare
verify_prepared = READER.verify_prepared
native_products = READER.native_products

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    prepare(parser.parse_args().output)
