#!/usr/bin/env python3
"""Manual exact-artifact OCI resource qualification, with retained failed commands."""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.ci_rust_artifacts import Suite
from tools.phase2_operator_process import require
from tools.phase3_resource_profile import integer
from tools.phase3_resource_rust import run

NAME = "http::network::tests::resource::bounded_oci_pool_resource_checkpoint"
SUITE = Suite("crates/latent-oci/Cargo.toml", "latent_oci", "src/lib.rs", NAME, frozenset({NAME}), True)


def validate_observations(value, _binary):
    require(value["schemaVersion"] == "latent.phase3.oci-resource.v1"
            and value["status"] == "checkpoint-passed" and value["ceilings"] == [1, 2]
            and value["cyclesPerPool"] == 4 and value["universalPerformanceClaim"] is False,
            "resource-oci-report-scope")
    rows = value["observations"]
    require(len(rows) == 48, "resource-oci-population")
    for ceiling in (1, 2):
        for kind in ("token", "dns", "redirect"):
            selected = [row for row in rows if row["kind"] == kind and row["ceiling"] == ceiling]
            require([row["phase"] for row in selected] == ["fixed", "active", "recovery", "cold",
                    "warm", "warm", "warm", "shutdown"], "resource-oci-phase-population")
            for row in selected:
                require(row["os"]["processId"] == value["fixed"]["processId"]
                        and integer(row["os"]["residentMemoryBytes"]) > 0, "resource-oci-process-owner")
                require(integer(row["usage"]["inFlight"]) <= ceiling
                        and integer(row["network"]["connections"]) <= integer(row["network"]["maximumConnections"])
                        and integer(row["network"]["reservedConnectionBytes"]) <= integer(row["network"]["maximumConnectionBytes"])
                        and integer(row["bearer"]["retainedTokenBytes"]) <= integer(row["bearer"]["maximumTokenBytes"]),
                        "resource-oci-configured-bound")
                if row["phase"] != "active":
                    require(all(integer(row[group][key]) == 0 for group, keys in (
                        ("usage", ("inFlight", "retainedPackages", "retainedBytes")),
                        ("bearer", ("activeAcquisitions", "waitingAcquisitions", "reservedAcquisitionBytes")),
                        ("network", ("connections", "activeResolvers", "waitingResolvers",
                                     "reservedConnectionBytes", "reservedRedirectBytes"))) for key in keys),
                        "resource-oci-active-ownership-retained")
                if row["phase"] in ("cold", "warm"):
                    require(integer(row["elapsedNanos"]) > 0, "resource-oci-latency-missing")
            active = selected[1]
            require(integer(active["usage"]["inFlight"]) == ceiling, "resource-oci-ceiling-not-exercised")
            if kind == "token":
                require(active["bearer"]["activeAcquisitions"] == 1
                        and active["bearer"]["waitingAcquisitions"] == ceiling - 1, "resource-oci-token-population")
            elif kind == "dns":
                require(active["network"]["activeResolvers"] == 1
                        and active["network"]["waitingResolvers"] == ceiling - 1, "resource-oci-dns-population")
            else:
                require(active["network"]["reservedRedirectBytes"] == ceiling * 16384,
                        "resource-oci-redirect-population")
            require(len({(row["bearer"]["retainedTokenBytes"], row["network"]["reservedResolverBytes"])
                    for row in selected if row["phase"] in ("cold", "warm")}) == 1, "resource-oci-cache-plateau")
            closed = selected[-1]
            require(all(closed[key]["closed"] is True for key in ("usage", "bearer", "network"))
                    and closed["bearer"]["cachedTokens"] == closed["network"]["retainedDnsAnswers"] == 0,
                    "resource-oci-shutdown-incomplete")
    require(all(value["fixed"][key] == value["retired"][key] for key in
                ("processId", "threadCount", "socketCount")), "resource-oci-peer-retirement")
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--host-condition", action="append", default=[])
    args = parser.parse_args()
    require(len(args.host_condition) <= 8 and all(re.fullmatch(r"[a-z0-9-]{1,96}", label)
            for label in args.host_condition), "resource-host-label-bound")
    return run(args, suite=SUITE, package="latent-oci", report_env="LSF_PHASE3_OCI_RESOURCE_REPORT",
               validator=validate_observations, ignored=True)


if __name__ == "__main__":
    raise SystemExit(main())
