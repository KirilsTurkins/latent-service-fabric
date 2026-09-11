"""Pinned kind iptables programming evidence; this does not test connectivity."""
from __future__ import annotations

from ipaddress import IPv4Address
import re
import shlex
import time

from tools.optimization_evidence.common import require
from tools.optimization_docker.owned import stamp

MAX_BYTES = 1024**2
MAX_LINES = 8192
MAX_ATTEMPTS = 20
TIMEOUT_NANOS = 120 * 10**9
COMMANDS = {table: ["iptables-save", "-t", table] for table in ("nat", "filter")}


def _table(raw, table):
    require(isinstance(raw, bytes) and 0 < len(raw) <= MAX_BYTES, "kubernetes-proxy-byte-bound")
    try:
        lines = raw.decode("ascii").splitlines()
    except UnicodeDecodeError as error:
        raise ValueError("kubernetes-proxy-ascii") from error
    require(len(lines) <= MAX_LINES and all(len(line) <= 16384 for line in lines),
            "kubernetes-proxy-line-bound")
    chains, begun, committed = {}, False, False
    for line in lines:
        if not line or line.startswith("#"):
            continue
        if line == "*" + table:
            require(not begun, "kubernetes-proxy-duplicate-table")
            begun = True
            continue
        require(begun and not committed, "kubernetes-proxy-table-framing")
        if line == "COMMIT":
            committed = True
        elif line.startswith(":"):
            match = re.fullmatch(r":([A-Za-z0-9_-]{1,64}) (?:ACCEPT|DROP|-) \[[0-9]{1,20}:[0-9]{1,20}\]", line)
            require(match is not None and match[1] not in chains and len(chains) < 2048,
                    "kubernetes-proxy-chain-declaration")
            chains[match[1]] = []
        else:
            tokens = shlex.split(line, posix=True)
            require(3 <= len(tokens) <= 128 and tokens[0] == "-A" and tokens[1] in chains,
                    "kubernetes-proxy-rule-framing")
            chains[tokens[1]].append(tokens[2:])
    require(begun and committed, "kubernetes-proxy-incomplete-table")
    return chains


def _option(rule, key):
    positions = [index for index, value in enumerate(rule) if value == key]
    require(len(positions) <= 1 and all(index + 1 < len(rule) for index in positions),
            "kubernetes-proxy-duplicate-rule-option")
    return rule[positions[0] + 1] if positions else None


def _comment(value):
    return ["-m", "comment", "--comment", value]


def _route(nat, filtered, namespace, target):
    ip, pod_ip = str(IPv4Address(target["cluster_ip"])), str(IPv4Address(target["pod_ip"]))
    name = target["service_name"]
    require(isinstance(name, str) and re.fullmatch(r"[a-z0-9-]{1,63}", name),
            "kubernetes-proxy-service-name")
    label = namespace + "/" + name + ":grpc"
    result = {key: target[key] for key in ("service_name", "service_uid", "cluster_ip", "pod_uid", "pod_ip")}
    result.update(service_chain=None, endpoint_chain=None, ready=False, reason=None)

    def unavailable(reason):
        result["reason"] = reason
        return result

    portals = _comment("kubernetes service portals") + ["-j", "KUBE-SERVICES"]
    if nat.get("PREROUTING", []).count(portals) != 1 or nat.get("OUTPUT", []).count(portals) != 1:
        return unavailable("service-portal-hook-not-programmed")
    if "KUBE-SERVICES" not in filtered:
        return unavailable("service-filter-chain-not-programmed")
    # A matching Service reject is relevant even while its NAT route is absent.
    for rule in (rule for rules in filtered.values() for rule in rules):
        if (_option(rule, "-d") in (ip, ip + "/32")
                and _option(rule, "-p") in (None, "tcp")
                and _option(rule, "--dport") in (None, "7070")
                and _option(rule, "-j") in ("REJECT", "DROP")):
            return unavailable("service-filter-reject-present")
    matching = [rule for rule in nat.get("KUBE-SERVICES", [])
                if _option(rule, "-d") in (ip, ip + "/32")
                and _option(rule, "-p") in (None, "tcp")
                and _option(rule, "--dport") in (None, "7070")]
    if len(matching) != 1:
        return unavailable("service-route-missing-or-ambiguous")
    service = _option(matching[0], "-j")
    prefix = ["-d", ip + "/32", "-p", "tcp"] + _comment(label + " cluster IP")
    if (not isinstance(service, str) or not re.fullmatch(r"KUBE-SVC-[A-Z0-9]{16}", service)
            or matching[0] != prefix + ["-m", "tcp", "--dport", "7070", "-j", service]):
        return unavailable("service-route-not-exact")
    result["service_chain"] = service
    rules = nat.get(service, [])
    destinations = [rule for rule in rules if (_option(rule, "-j") or "").startswith("KUBE-SEP-")]
    if len(destinations) != 1:
        return unavailable("endpoint-route-missing-or-ambiguous")
    endpoint = _option(destinations[0], "-j")
    destination_rule = _comment(label + " -> " + pod_ip + ":7070") + ["-j", endpoint]
    # The only other permitted SVC rule is the pinned local-cluster masquerade rule.
    masquerade = ["!", "-s", "10.244.0.0/16"] + prefix + ["-m", "tcp", "--dport", "7070", "-j", "KUBE-MARK-MASQ"]
    if (not re.fullmatch(r"KUBE-SEP-[A-Z0-9]{16}", endpoint)
            or rules != [masquerade, destination_rule]):
        return unavailable("endpoint-selection-not-exact")
    result["endpoint_chain"] = endpoint
    expected = [["-s", pod_ip + "/32"] + _comment(label) + ["-j", "KUBE-MARK-MASQ"],
                ["-p", "tcp"] + _comment(label) + ["-m", "tcp", "-j", "DNAT", "--to-destination", pod_ip + ":7070"]]
    if nat.get(endpoint) != expected:
        return unavailable("endpoint-dnat-not-exact")
    result.update(ready=True, reason=None)
    return result


def validate(nat_raw, filter_raw, graph):
    """Return readiness for every graph target, preserving nonready rule evidence."""
    namespace = graph["namespace"]
    targets = graph["targets"]
    require(isinstance(namespace, str) and re.fullmatch(r"[a-z0-9-]{1,63}", namespace)
            and isinstance(targets, list) and 1 <= len(targets) <= 32,
            "kubernetes-proxy-target-bound")
    require(len({row["cluster_ip"] for row in targets}) == len(targets)
            and len({row["service_uid"] for row in targets}) == len(targets),
            "kubernetes-proxy-target-bijection")
    nat, filtered = _table(nat_raw, "nat"), _table(filter_raw, "filter")
    routes = [_route(nat, filtered, namespace, target) for target in targets]
    return {"ready": all(row["ready"] for row in routes), "routes": routes}


def wait(worker, graph, *, deadline, progress):
    """Read rules only, retaining every attempt before any client connection."""
    until = min(time.monotonic_ns() + TIMEOUT_NANOS, deadline)
    attempts = []
    for _ in range(MAX_ATTEMPTS):
        require(time.monotonic_ns() < until, "kubernetes-proxy-readiness-deadline")
        nat, nat_call = worker.command(COMMANDS["nat"])
        require(time.monotonic_ns() < until, "kubernetes-proxy-readiness-deadline")
        filtered, filter_call = worker.command(COMMANDS["filter"])
        result = validate(nat, filtered, graph)
        attempt = {"nat_call": nat_call, "filter_call": filter_call,
                   "observed_nanos": stamp(), "result": result}
        attempts.append(attempt)
        progress(attempt)
        require(int(attempt["observed_nanos"]) <= until, "kubernetes-proxy-readiness-deadline")
        if result["ready"]:
            ready = stamp()
            require(int(ready) <= until, "kubernetes-proxy-readiness-deadline")
            return {"attempts": attempts, "ready_nanos": ready}
        time.sleep(0.1)
    raise TimeoutError("kubernetes-proxy-readiness-attempt-bound")
