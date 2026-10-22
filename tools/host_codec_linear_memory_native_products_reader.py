"""Closed v7 linear-notification/context/native-audit schema; no acquisition tuple.

Only a separately reviewed immutable success wrapper may acquire products.
Old cohorts and their fixed identities remain independently authenticated.
"""
from tools.host_codec_native_products_reader import FrozenHostCodecProducts, _producer_contract

COHORT = 'wasmtime-48.0.7-latent-value-table-store-registry-funcrefs-resource-types-linear-notification-retained-context-memory-v7'
SCOPE = 'ordinary-host-retained-activation-context-and-linear-allocation-notifications-codec-table-and-selected-Store-instance-buffer-registry-FuncRefs-container-resource-substitutions-original-memory-and-selected-c-public-async-type-sync-core-admission-and-authenticated-c-ready-handoff-and-closed-guest-trap-diagnostics-and-exact-native-thread-audit-codec; direct-Core-HostFunc-construction, shared-preparation-closures, concurrent-task, hostcall, request ingress and discarded scaffolding and later hostcall copies, legacy framing and serialized controller frames excluded'


def producer_contract(raw):
    return _producer_contract(raw, 24, 114)


class FrozenHostCodecLinearMemoryProducts(FrozenHostCodecProducts):
    cohort, scope = COHORT, SCOPE
    control_count, command_count = 114, 51
    job_name = ('Original ledger codec table Store registry FuncRefs resource context '
        'ownership and diagnostics')

    def _producer_contract(self, raw):
        return producer_contract(raw)
