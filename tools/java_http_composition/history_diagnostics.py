"""Finite supported paging, concurrent readers and real terminal-history expiry.

Only membership is pinned by a cursor. Node outcomes may progress between
pages. Expired history remains unavailable and says nothing about an external
mutation's disposition.
"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import time

from tools.java_http_composition import context, inspection
from tools.java_http_composition.node import ADAPTER, idle
from tools.phase2_operator_process import read_json, require, write_json
from tools.rust_capsule_node import RecordingClient

MAX_PAGES = 4
MAX_BYTES = 65536
MAX_TOKEN_BYTES = 160
READERS = 2
RETENTION_MILLIS = 120000


def page(data, *, tree, size=1):
    require(type(data["schemaVersion"]) is int and data["schemaVersion"] == 1,
            "java-history-version")
    require(type(data["cursorExpired"]) is bool, "java-history-expiry-presence")
    require(data["externalCompletion"] == "unknown", "java-history-no-external-disposition-proof")
    require(data["retainedHistoryOnly"] is True if not tree else type(data["historyAvailable"]) is bool,
            "java-history-scope")
    require(isinstance(data["nodes"], list) and len(data["nodes"]) <= size
            and len(json.dumps(data).encode("utf-8")) <= MAX_BYTES, "java-history-page-bound")
    token = data["nextPageToken"]
    require(token is None or isinstance(token, str) and token.isascii()
            and 0 < len(token) <= MAX_TOKEN_BYTES, "java-history-cursor-bound")
    identifiers = [row["activationId"] for row in data["nodes"]]
    require(all(isinstance(value, str) and 0 < len(value.encode("utf-8")) <= 512 for value in identifiers)
            and len(set(identifiers)) == len(identifiers), "java-history-node-identities")
    return identifiers


def collect(client, arguments, first, *, tree):
    pages, identities, token, seen = [first], page(first, tree=tree), first["nextPageToken"], set()
    while token is not None:
        require(len(pages) < MAX_PAGES and token not in seen, "java-history-page-cycle-or-count")
        seen.add(token)
        observed = client.call(*arguments, "--page-size", 1, "--page-token", token)["data"]
        require(not observed["cursorExpired"] and (not tree or observed["historyAvailable"]),
                "java-history-unavailable-during-paging")
        additional = page(observed, tree=tree)
        require(not set(additional).intersection(identities), "java-history-repeated-node")
        identities.extend(additional)
        require(len(identities) <= 128, "java-history-node-count")
        pages.append(observed)
        token = observed["nextPageToken"]
    return {"pages": pages, "activationIds": identities}


def expired(data):
    page(data, tree=True)
    return data["historyAvailable"] is False and data["cursorExpired"] is True \
        and not data["nodes"] and data["nextPageToken"] is None


def _reader(client, directory, root):
    directory.mkdir(mode=0o700)
    reader = RecordingClient(client.executable, directory, client.cancellation, client.deadline,
                             evidence=directory / "controls", invocation_timeout_millis=120000)
    reader.environment = dict(client.environment)
    reader.config = client.config
    first = reader.call("activation", "tree", root, "--page-size", 1)["data"]
    observed = collect(reader, ("activation", "tree", root), first, tree=True)
    observed.update(readCalls=reader.calls, originalDeadline=reader.deadline)
    require(reader.calls <= MAX_PAGES, "java-history-concurrent-call-bound")
    return observed


def authority(client, root, cursor):
    """Real tenant/invoke-only probes; opaque IDs never confer record access."""
    original, before, result = client.config, inspection.owners(client), {}
    for name, token, tenant in (("wrong-tenant", inspection.WRONG_TENANT_TOKEN, "other-examples"),
                               ("invoke-only", inspection.INVOKER_TOKEN, "examples")):
        settings = deepcopy(read_json(original))
        settings["profiles"][0].update(token=token, tenant=tenant)
        selected = client.directory / (name + "-history-client.json")
        write_json(selected, settings)
        client.config = selected
        try:
            observations = {}
            for kind, args in (("tree", ("activation", "tree", root, "--page-token", cursor)),
                               ("roots", ("activation", "roots", "--service", ADAPTER))):
                reply = client.call(*args, "--page-size", 1, codes=(0, 4, 6))
                if name == "wrong-tenant" and reply["category"] == "success":
                    data = reply["data"]
                    require(not page(data, tree=kind == "tree") and data["nextPageToken"] is None
                            and data["externalCompletion"] == "unknown"
                            and (kind != "tree" or data["historyAvailable"] is False),
                            "java-history-foreign-record-disclosed")
                else:
                    require(reply["category"] == "platform-failure"
                            and reply["error"]["code"] == "permission-denied",
                            "java-history-operator-authority-required")
                observations[kind] = reply
            result[name] = observations
        finally:
            client.config = original
    require(inspection.owners(client) == before, "java-history-inspection-acquired-execution-owners")
    return result


def qualify(client, host, output):
    output.mkdir(mode=0o700)
    started = int(time.time() * 1000)
    originals = [context.capture_http(client, host) for _ in range(2)]
    roots = [row["tree"]["nodes"][0]["rootActivationId"] for row in originals]
    require(len(set(roots)) == 2, "java-history-distinct-original-roots")
    arguments = ("activation", "roots", "--service", ADAPTER, "--from-unix-millis", started)
    root_page = client.call(*arguments, "--page-size", 1)["data"]
    require(page(root_page, tree=False) and root_page["nextPageToken"], "java-history-real-root-pagination")
    newer = context.capture_http(client, host)
    newer_id = newer["tree"]["nodes"][0]["rootActivationId"]
    selected = collect(client, arguments, root_page, tree=False)
    require(set(selected["activationIds"]) == set(roots) and newer_id not in selected["activationIds"],
            "java-history-original-root-membership-horizon")
    root = roots[0]
    first = client.call("activation", "tree", root, "--page-size", 1)["data"]
    require(first["historyAvailable"] and first["nextPageToken"], "java-history-real-child-pagination")
    terminal_time = time.monotonic()
    tree = collect(client, ("activation", "tree", root), first, tree=True)
    require(len(tree["activationIds"]) == 2, "java-history-original-parent-child")
    scoped = authority(client, root, first["nextPageToken"])
    with ThreadPoolExecutor(max_workers=READERS) as workers:
        pending = [workers.submit(_reader, client, output / f"reader-{index}", root) for index in range(READERS)]
        concurrent = [future.result(timeout=max(.001, client.deadline - time.monotonic())) for future in pending]
    require(all(set(row["activationIds"]) == set(tree["activationIds"]) and row["originalDeadline"] == client.deadline
                for row in concurrent), "java-history-concurrent-original-membership")
    require(client.deadline - terminal_time > RETENTION_MILLIS / 1000 + 3, "java-history-original-deadline-too-short")
    # This waits for the configured native retention owner, not guest readiness.
    # The original outer deadline remains unchanged and cancellation is polled.
    while time.monotonic() < terminal_time + RETENTION_MILLIS / 1000 + .1:
        client.cancellation.check()
        require(time.monotonic() < client.deadline, "java-history-original-deadline")
        time.sleep(max(0, min(.1, terminal_time + RETENTION_MILLIS / 1000 + .1 - time.monotonic())))
    unavailable = client.call("activation", "tree", root, "--page-size", 1,
                              "--page-token", first["nextPageToken"])["data"]
    require(expired(unavailable), "java-history-original-cursor-expiration")
    result = {"status": "passed", "rootPaging": selected, "treePaging": tree, "authority": scoped,
        "concurrentReaders": concurrent,
        "newRootExcludedByOriginalCursor": newer_id, "expiredHistory": unavailable,
        "configuredRetentionMillis": RETENTION_MILLIS, "externalMutationDisposition": "unknown",
        "cleanup": idle(client)}
    write_json(output / "observation.json", result)
    return result
