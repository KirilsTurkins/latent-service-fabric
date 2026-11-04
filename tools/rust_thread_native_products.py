"""One immutable 193-control Rust40 original-component native origin.

This authenticates native products and source controls, never signed guest
progress, checkpoints, or general ThreadPool runtime qualification.
"""
from pathlib import Path
import hashlib
import sys

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.host_codec_native_products_reader import FrozenHostCodecProducts, _producer_contract
from tools.host_codec_owned_reply_native_products_reader import CLI_CONTROL
from tools.phase2_operator_process import require

SOURCE = 'b422af24d86344ac7abb8b8fa56c3782aab63915'
RUN = 39884205952
HISTORICAL_JOB = 120188455407
JOB = 124001233201
BRANCH = 'feat/rust-sync-profile-20261023'
HISTORICAL_ARTIFACT = {'id': 12472447074, 'size_in_bytes': 70987235, 'digest': 'sha256:5a4c0f0cc2ebf8f307ad7d657323ed4c53afc61cd9bb2bc318d564e9b23a4e58'}
ARTIFACT = {'id': 12969252228, 'size_in_bytes': 70987125, 'digest': 'sha256:3a3cc9c4ceb585bb51e5780f09b34339f72feaf6a2ecaabf1e359932745bb066'}
HISTORICAL_RECEIPTS = {'native-products.json': {'bytes': 135023, 'sha256': 'sha256:9172517704fd93fd1e5311b2ac9a12aa2df4d7ff9e255804b27a47fb9276c5aa'}, 'source-inputs.json': {'bytes': 24881, 'sha256': 'sha256:c24f170cb7890fa25b363a0219138d3629149849e4d7cc299ad53313948da6da'}}
RECEIPTS = {'native-products.json': {'bytes': 135020, 'sha256': 'sha256:3f030c32826880b7338982e4162fbd0d50ed86ae187b0677ea71c771521b48be'}, 'source-inputs.json': HISTORICAL_RECEIPTS['source-inputs.json']}
PRODUCER_SHA256 = '165497353226b386a9cc66e198b06e556248b672a91edbdba52c040b56603d5c'
ALLOCATION_COHORT = 'wasmtime-48.0.7-latent-value-table-store-registry-funcrefs-resource-types-linear-notification-retained-context-host-future-owned-reply-memory-v9'
COHORT = 'wasmtime-48.0.7-latent-value-table-store-registry-funcrefs-resource-types-linear-notification-retained-context-host-future-owned-reply-retained-capability-directories-blob-streaming-shared-tables-runtime-timer-strong-weak-session-core-stats-c-canonical-system-stack-native-only-cumulative-retirement-physical-result-owner-box-handle-owned-text-call-buffers-rust-context40-authenticated-original-memory-v16'
SCOPE = 'original-copied-Work-input-and-OwnedCapabilityResponse-byte-buffers-and-original-HandleEntry-row-and-every-owned-resource-text-copy-and-pending-clock-row-followed-by-ordinary-physical-native-only-accounting-retention-separate-from-last-ordinary-owner-cumulative-child-retirement-and-original-sealed-session-Core-and-Stats-strong-and-weak-Arc-backing-including-both-private-billing-Arcs-owned-identity-text-and-fixed-handle-slots-and-selected-C-canonical-realloc-private-System-stack-routing-and-ordinary-runtime-and-timer-strong-and-weak-Arc-backing-including-private-billing-Arc-and-ordinary-host-blob-fixed-Vec-and-streaming-HTTP-fixed-Vec-and-two-private-Shared-Arc-storage-shapes-and-three-retained-capability-directory-backings-and-six-closed-context-reply-buffers-and-concrete-callback-future-box-and-retained-activation-context-and-linear-allocation-notifications-codec-table-and-selected-Store-instance-buffer-registry-FuncRefs-container-resource-substitutions-original-memory-and-selected-c-public-async-type-sync-core-admission-and-authenticated-c-ready-handoff-and-closed-guest-trap-diagnostics-and-exact-native-thread-audit-codec-and-CLI-projection-and-source-bound-Rust40-original-object-callback-canonical-result-async-public-sync-core-normal-component-authentication-and-paid-profile-admission-and-real-private-dispatch-helper-execution; direct-Core-HostFunc-construction, shared-preparation-closures, concurrent-task, other-hostcall-values-custom-Lower-shared-interior-error-owned-copies-and-opaque-accessor-scheduler-frames, request ingress and discarded scaffolding and other hostcall copies, shared broker and compiled-plan preparation and transitive provider payload/transport/queue graphs, legacy framing and serialized controller frames excluded'
STAGES = ('source-revision', 'rust-version', 'normal-host-build', 'original-host-memory-list', 'original-host-memory-run', 'result-owner-list', 'result-owner-run', 'result-wire-list', 'result-wire-run', 'result-capacity-list', 'result-capacity-run', 'actual-host-codec-list', 'actual-host-codec-run', 'actual-dynamic-allocation-hook-list', 'actual-dynamic-allocation-hook-run', 'raw-input-lifetime-list', 'raw-input-lifetime-run', 'result-lifetime-list', 'result-lifetime-run', 'original-accounting-list', 'original-accounting-run', 'child-capacity-list', 'child-capacity-run', 'c-public-async-type-list', 'c-public-async-type-run', 'c-public-sync-abi-list', 'c-public-sync-abi-run', 'journal-result-retirement-list', 'journal-result-retirement-run', 'ordinary-backend-list', 'ordinary-backend-run', 'actual-native-table-owner-list', 'actual-native-table-owner-run', 'actual-native-store-owner-list', 'actual-native-store-owner-run', 'closed-guest-trap-diagnostics-list', 'closed-guest-trap-diagnostics-run', 'actual-native-registry-owner-list', 'actual-native-registry-owner-run', 'actual-native-funcrefs-owner-list', 'actual-native-funcrefs-owner-run', 'c-ready-handoff-list', 'c-ready-handoff-run', 'resource-substitutions-list', 'resource-substitutions-run', 'actual-linear-allocation-notifications-list', 'actual-linear-allocation-notifications-run', 'native-thread-audit-codec-list', 'native-thread-audit-codec-run', 'retained-activation-context-list', 'retained-activation-context-run', 'actual-host-future-owner-list', 'actual-host-future-owner-run', 'c-canonical-wait-routes-list', 'c-canonical-wait-routes-run', 'actual-owned-context-reply-list', 'actual-owned-context-reply-run', 'cli-native-thread-audit-projection-list', 'cli-native-thread-audit-projection-run', 'actual-retained-capability-directory-list', 'actual-retained-capability-directory-run', 'actual-streaming-table-shared-owner-list', 'actual-streaming-table-shared-owner-run', 'actual-blob-table-owner-list', 'actual-blob-table-owner-run', 'original-session-table-native-owner-list', 'original-session-table-native-owner-run', 'actual-runtime-timer-strong-weak-owner-list', 'actual-runtime-timer-strong-weak-owner-run', 'original-session-native-owner-list', 'original-session-native-owner-run', 'original-session-optional-shared-owner-list', 'original-session-optional-shared-owner-run', 'c-canonical-private-system-stack-list', 'c-canonical-private-system-stack-run', 'actual-native-only-cumulative-retirement-list', 'actual-native-only-cumulative-retirement-run', 'original-handle-owned-text-list', 'original-handle-owned-text-run', 'original-handle-native-owner-list', 'original-handle-native-owner-run', 'original-pending-clock-handle-native-owner-list', 'original-pending-clock-handle-native-owner-run', 'original-call-native-buffer-owner-list', 'original-call-native-buffer-owner-run', 'rust-original-catalogue-list', 'rust-original-catalogue-run', 'rust-normal-component-list', 'rust-normal-component-run', 'rust-private-dispatch-engine-list', 'rust-private-dispatch-engine-run')


class _FrozenRustOriginalNativeProducts(FrozenHostCodecProducts):
    cohort, scope = COHORT, SCOPE
    control_count, command_count = 193, 91
    job_name = 'Original ledger shared tables and runtime memory ownership diagnostics'

    def __init__(self):
        super().__init__(source=SOURCE, run=RUN, job=JOB, artifact=ARTIFACT,
            receipts=RECEIPTS, branch=BRANCH, event='workflow_dispatch')

    def _valid_stages(self, stages):
        return stages == STAGES

    def _producer_contract(self, raw):
        require(type(raw) is bytes and hashlib.sha256(raw).hexdigest() == PRODUCER_SHA256,
            'rust-original-native-exact-frozen-producer')
        return _producer_contract(raw, 44, 193, extra_control=CLI_CONTROL, recipe_count=24)

    def validate_record(self, record, snapshot, native, materials):
        require(type(record) is dict and record.get('wasmtimeAllocationCohort') == ALLOCATION_COHORT,
            'rust-original-native-unchanged-wasmtime-allocation-cohort')
        original_schema = dict(record)
        del original_schema['wasmtimeAllocationCohort']
        super().validate_record(original_schema, snapshot, native, materials)


READER = _FrozenRustOriginalNativeProducts()
prepare = READER.prepare
verify_prepared = READER.verify_prepared
native_products = READER.native_products

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    prepare(parser.parse_args().output)
