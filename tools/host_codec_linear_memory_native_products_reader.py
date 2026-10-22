"""Closed v6 linear-notification/native-audit schema; no acquisition tuple.

Only a separately reviewed immutable success wrapper may acquire products.
Old cohorts and their fixed identities remain independently authenticated.
"""
from tools.host_codec_native_products_reader import FrozenHostCodecProducts, _producer_contract

COHORT = 'wasmtime-48.0.7-latent-value-table-store-registry-funcrefs-resource-types-linear-notification-memory-v6'
SCOPE = 'ordinary-host-linear-allocation-notifications-codec-table-and-selected-Store-instance-buffer-registry-FuncRefs-container-resource-substitutions-original-memory-and-selected-c-public-async-type-sync-core-admission-and-authenticated-c-ready-handoff-and-closed-guest-trap-diagnostics-and-exact-native-thread-audit-codec; direct-Core-HostFunc-construction, shared-preparation-closures, concurrent-task, hostcall, request-context transitive buffers, legacy framing and serialized controller frames excluded'


def producer_contract(raw):
    return _producer_contract(raw, 23, 103)


class FrozenHostCodecLinearMemoryProducts(FrozenHostCodecProducts):
    cohort, scope = COHORT, SCOPE
    control_count, command_count = 103, 49
    job_name = ('Original ledger linear codec table Store registry FuncRefs resource '
        'ownership and diagnostics')

    def _producer_contract(self, raw):
        return producer_contract(raw)
