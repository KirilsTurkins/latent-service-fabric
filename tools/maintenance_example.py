#!/usr/bin/env python3
"""Finite synthetic read-only sweep; no state mutations, timers or credentials."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

MAX_RECORDS = 64
MAX_PAGE = 8
MAX_PAGE_BYTES = 2048
MAX_INPUT_BYTES = 16 * 1024


class MaintenanceError(ValueError):
    pass


def require(condition, reason):
    if not condition:
        raise MaintenanceError(reason)


def canonical(value):
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode()


class ReadOnlySweep:
    """Application semantics over an immutable synthetic snapshot, not LSF storage."""
    def __init__(self, tenant, records, *, last_trusted_time=0):
        require(isinstance(tenant, str) and re.fullmatch(r"[a-z0-9-]{1,32}", tenant), "tenant")
        require(isinstance(records, list) and len(records) <= MAX_RECORDS, "record-bound")
        selected = []
        for row in records:
            require(isinstance(row, dict) and set(row) == {"id", "expiresAtMillis"}, "record-fields")
            require(isinstance(row["id"], str) and re.fullmatch(r"[a-z0-9-]{1,64}", row["id"]), "record-id")
            require(type(row["expiresAtMillis"]) is int and 0 <= row["expiresAtMillis"] < 2**64, "expiry")
            selected.append(dict(row))
        selected.sort(key=lambda row: row["id"])
        require(len({row["id"] for row in selected}) == len(selected), "duplicate-record")
        require(type(last_trusted_time) is int and 0 <= last_trusted_time < 2**64, "trusted-time")
        self.tenant, self.records, self.last_trusted_time = tenant, tuple(selected), last_trusted_time
        self.identity = hashlib.sha256(canonical({"tenant": tenant, "records": selected})).hexdigest()

    def _cursor(self, position):
        # Opaque progress, deliberately not an authorization bearer or secret.
        raw = f"maintenance-observation-v1:{self.tenant}:{self.identity}:{position}".encode()
        return "page:" + hashlib.sha256(raw).hexdigest()

    def page(self, *, authenticated_tenant, allowed_commands, trusted_now, cursor=None,
             maximum_records=MAX_PAGE, maximum_bytes=MAX_PAGE_BYTES, cancelled=lambda: False):
        require(authenticated_tenant == self.tenant and "observe-expiry" in allowed_commands, "unauthorized")
        require(type(trusted_now) is int and self.last_trusted_time <= trusted_now < 2**64, "clock-regression")
        require(type(maximum_records) is int and 1 <= maximum_records <= MAX_PAGE, "page-bound")
        require(type(maximum_bytes) is int and 256 <= maximum_bytes <= MAX_PAGE_BYTES, "byte-bound")
        require(cursor is None or isinstance(cursor, str) and re.fullmatch(r"page:[0-9a-f]{64}", cursor), "cursor-shape")
        if cursor is None:
            position = 0
        else:
            positions = [index for index in range(len(self.records) + 1) if self._cursor(index) == cursor]
            require(len(positions) == 1, "stale-or-foreign-cursor")
            position = positions[0]
        observed = []
        while position < len(self.records) and len(observed) < maximum_records:
            if cancelled():
                return self._result(observed, position, "interrupted")
            row = self.records[position]
            candidate = {"id": row["id"], "expired": trusted_now >= row["expiresAtMillis"]}
            result = self._result([*observed, candidate], position + 1, "complete-page")
            if len(canonical(result)) > maximum_bytes:
                require(observed, "single-record-exceeds-page-byte-bound")
                break
            observed.append(candidate)
            position += 1
        return self._result(observed, position, "complete-page")

    def _result(self, observed, position, disposition):
        return {"schemaVersion": "latent.maintenance.observation-page.v1", "snapshot": self.identity,
                "records": observed, "nextCursor": self._cursor(position) if position < len(self.records) else None,
                "disposition": disposition, "mutations": 0, "platformDurability": False}

    def access_allowed(self, identifier, *, authenticated_tenant, trusted_now):
        require(authenticated_tenant == self.tenant, "unauthorized")
        require(type(trusted_now) is int and self.last_trusted_time <= trusted_now < 2**64, "clock-regression")
        rows = [row for row in self.records if row["id"] == identifier]
        return len(rows) == 1 and trusted_now < rows[0]["expiresAtMillis"]


def observe_fixture(path, trusted_now):
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= MAX_INPUT_BYTES, "fixture-file")
    raw = path.read_bytes()
    require(len(raw) <= MAX_INPUT_BYTES, "fixture-byte-bound")
    def pairs(rows):
        result = {}
        for key, value in rows:
            require(key not in result, "duplicate-json-key")
            result[key] = value
        return result
    fixture = json.loads(raw, object_pairs_hook=pairs)
    require(set(fixture) == {"schemaVersion", "tenant", "records"}
            and fixture["schemaVersion"] == "latent.maintenance.synthetic-input.v1", "fixture-profile")
    sweep = ReadOnlySweep(fixture["tenant"], fixture["records"])
    pages, cursor = [], None
    for _ in range(MAX_RECORDS):
        page = sweep.page(authenticated_tenant=fixture["tenant"], allowed_commands={"observe-expiry"},
                          trusted_now=trusted_now, cursor=cursor)
        pages.append(page)
        cursor = page["nextCursor"]
        if cursor is None:
            break
    require(cursor is None, "finite-sweep-incomplete")
    return {"schemaVersion": "latent.maintenance.synthetic-observation.v1", "execution": "synthetic-read-only",
            "pages": pages, "guestExecution": False, "durableSchedule": False, "mutations": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--synthetic-now-millis", type=int, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(observe_fixture(args.fixture, args.synthetic_now_millis), sort_keys=True))
        return 0
    except (MaintenanceError, OSError, ValueError, RecursionError):
        print('{"schemaVersion":"latent.maintenance.synthetic-observation.v1","status":"failed"}', file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
