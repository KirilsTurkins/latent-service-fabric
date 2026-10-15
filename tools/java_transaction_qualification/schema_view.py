"""Check schema-bound descriptive views; native review remains authoritative."""
from __future__ import annotations

import hashlib

from . import configuration as cfg, lifecycle, recovery
from .inputs import require


def _binding(schema):
    recovery.original_digest(schema)
    # session::codec::key_prefix: the campaign uses namespace scope, incarnation 1,
    # with no entity. session::version::scope_digest also binds the exact schema.
    prefix = bytearray(b"state-v1\0")
    for value in (cfg.TENANT, cfg.NAMESPACE):
        raw = value.encode("utf-8")
        prefix.extend(len(raw).to_bytes(2, "little"))
        prefix.extend(raw)
    prefix.extend((1).to_bytes(8, "little"))
    prefix.append(0)
    return hashlib.sha256(b"lsf-namespace-view-v2\0" + prefix + schema.encode("ascii")).digest()


def advanced(previous, current, original_item, target_item):
    old, new = bytes(recovery.original_view(previous)), bytes(recovery.original_view(current))
    # Re-read each retained, digest-bound companion using the existing collector
    # path. These expected identities are observations, never decoder grants.
    original_schema, target_schema = lifecycle.schema(original_item), lifecycle.schema(target_item)
    require(original_schema != target_schema
            and old[3:35] == _binding(original_schema) and new[3:35] == _binding(target_schema)
            and old[35:43] == new[35:43] == (1).to_bytes(8, "little"),
            "actual-native-schema-view-binding")
    generation, epoch = int.from_bytes(old[43:51], "little"), int.from_bytes(old[51:59], "little")
    # MigrationProgress::result_namespace/result_history use checked_add(1).
    require(generation < 2**64 - 1 and epoch < 2**64 - 1
            and int.from_bytes(new[43:51], "little") == generation + 1
            and int.from_bytes(new[51:59], "little") == epoch + 1
            and new[59:67] == old[59:67], "actual-native-schema-history-advanced")
