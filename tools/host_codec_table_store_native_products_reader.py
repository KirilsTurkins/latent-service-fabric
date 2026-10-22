"""Closed v2 table/Store producer schema, without acquisition or success pins.

An immutable wrapper may use this class only after the actual complete producer
archive has passed independent review. Source/schema controls are not a native
product result, and this module cannot select a branch tip.
"""
from tools.host_codec_native_products_reader import FrozenHostCodecProducts, _producer_contract

COHORT = 'wasmtime-48.0.7-latent-value-table-store-memory-v2'
SCOPE = ('ordinary-host-codec-table-and-selected-Store-instance-buffer-original-memory-and-'
    'selected-c-public-async-type-sync-core-admission-and-closed-guest-trap-diagnostics; '
    'registry, FuncRefs, concurrent-task, hostcall, request-context transitive buffers, '
    'legacy framing and serialized controller frames excluded')


def producer_contract(raw):
    return _producer_contract(raw, 17, 81)


class FrozenHostCodecTableStoreProducts(FrozenHostCodecProducts):
    cohort, scope = COHORT, SCOPE
    control_count, command_count = 81, 37
    job_name = 'Original ledger, actual codec table Store ownership and closed diagnostics'

    def _producer_contract(self, raw):
        return producer_contract(raw)
