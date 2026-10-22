"""Closed v4 registry/FuncRefs producer schema; no acquisition pins or branch selection.

The separately reviewed immutable wrapper is success-gated on the whole actual
producer archive. This class alone cannot acquire or qualify native products.
"""
from tools.host_codec_native_products_reader import FrozenHostCodecProducts, _producer_contract

COHORT = 'wasmtime-48.0.7-latent-value-table-store-registry-funcrefs-memory-v4'
SCOPE = ('ordinary-host-codec-table-and-selected-Store-instance-buffer-registry-FuncRefs-container-'
    'original-memory-and-selected-c-public-async-type-sync-core-admission-and-authenticated-c-ready-'
    'handoff-and-closed-guest-trap-diagnostics; direct-Core-HostFunc-construction, shared-preparation-'
    'closures, concurrent-task, hostcall, request-context transitive buffers, legacy framing and '
    'serialized controller frames excluded')


def producer_contract(raw):
    return _producer_contract(raw, 20, 92)


class FrozenHostCodecFuncRefsProducts(FrozenHostCodecProducts):
    cohort, scope = COHORT, SCOPE
    control_count, command_count = 92, 43
    job_name = ('Original ledger, actual codec table Store registry FuncRefs ownership '
        'and closed diagnostics')

    def _producer_contract(self, raw):
        return producer_contract(raw)
