"""Decode the pinned original API journal, retaining its final failed exec."""
from tools.optimization_docker import client_evidence as client
from tools.optimization_evidence.common import decode, fields, require, sha256, uint
from .. import transport_evidence as transport

SANDBOX = "728faf335ecbb827c73bdb296babcba675afe0a398211a8f3b2d475d66e55311"


def failed_exec(row, container, lower, upper):
    fields(row, "ordinal provider operation container_id argv timeout_seconds started_nanos finished_nanos records failure")
    require(row["ordinal"] == 1871 and row["provider"] == "docker" and row["operation"] == "worker-exec"
            and row["container_id"] == container and row["failure"] == "EvidenceError"
            and row["argv"] == ["crictl", "rmp", SANDBOX] and row["timeout_seconds"] == 20,
            "kubernetes-full01-failed-exec-identity")
    start, end = transport._window(row["started_nanos"], row["finished_nanos"], lower, upper)
    require(isinstance(row["records"], list) and len(row["records"]) == 3, "kubernetes-full01-failed-exec-records")
    first, second, third = row["records"]
    fields(first, "request receipt response")
    request = {"AttachStdin": False, "AttachStdout": True, "AttachStderr": True, "Tty": False,
        "Privileged": False, "Cmd": ["timeout", "--signal=TERM", "--kill-after=5s", "20s", "crictl", "rmp", SANDBOX]}
    require(first["request"] == request, "kubernetes-full01-failed-exec-command")
    created = transport._blob(first["response"])
    _, ready = transport._http(first["receipt"], method="POST", path=f"/v1.54/containers/{container}/exec", status=201,
        request=transport._wire(request), response=created, lower=start, upper=end)
    identity = fields(decode(created, transport.MAX_RESPONSE), "Id")
    identifier = transport._id(identity["Id"])
    fields(second, "request receipt response")
    body, output = transport._blob(second["request"]), transport._blob(second["response"])
    require(body == b'{"Detach":false,"Tty":false}', "kubernetes-full01-failed-exec-start")
    _, returned = transport._http(second["receipt"], method="POST", path=f"/v1.54/exec/{identifier}/start", status=200,
        request=body, response=output, lower=ready, upper=end)
    fields(third, "receipt response")
    raw = transport._blob(third["response"])
    transport._http(third["receipt"], method="GET", path=f"/v1.54/exec/{identifier}/json", status=200,
                    request=b"", response=raw, lower=returned, upper=end)
    final = decode(raw, transport.MAX_RESPONSE)
    require(final["ID"] == identifier and final["ContainerID"] == container
            and final["Running"] is False and type(final["ExitCode"]) is int and final["ExitCode"] == 1,
            "kubernetes-full01-original-nonzero-exit")
    stdout, stderr = transport._multiplexed(output)
    require(stdout == b"" and len(stderr) == 234 and SANDBOX.encode() in stderr
            and b"level=fatal" in stderr and b"code = NotFound" in stderr,
            "kubernetes-full01-original-notfound")
    return {"stdout": stdout, "stderr": stderr, "final_inspect": final,
            "exec_id": identifier, "original_failure": row["failure"]}, start, end


def validate(root, suite, boot):
    from ..failure_full import original_bytes
    data = original_bytes(root, "api.ndjson")
    lines = client._lines(data, transport.MAX_LINE_BYTES, 1872)
    require(len(lines) == 1872, "kubernetes-full01-journal-count")
    container = boot["nodes"]["worker"]["container_id"]
    nodes = {role: boot["nodes"][role]["container_id"] for role in ("worker", "control-plane")}
    rows, owner = [], None
    previous, upper = uint(suite["started_nanos"]), uint(suite["finished_nanos"])
    for index, (row, _, _) in enumerate(lines):
        require(type(row["ordinal"]) is int and row["ordinal"] == index, "kubernetes-full01-journal-order")
        if index == 1871:
            derived, start, end = failed_exec(row, container, previous, upper)
        elif row.get("provider") == "kubernetes":
            derived, start, end = transport._kubernetes(row, previous, upper)
        else:
            require(row.get("provider") == "docker", "kubernetes-full01-journal-provider")
            operation = row["operation"]
            if operation == "worker-identity":
                require(index == 0 and owner is None, "kubernetes-full01-worker-identity")
                derived, start, end = transport._identity(row, container, previous, upper)
                owner = derived["owner"]
            elif operation == "worker-exec":
                derived, start, end = transport._exec(row, container, previous, upper, owner=owner)
            elif operation == "worker-upload":
                derived, start, end = transport._upload(row, container, owner, previous, upper)
            elif operation == "worker-download":
                derived, start, end = transport._download(row, container, owner, previous, upper)
            else:
                require(operation == "node-stats", "kubernetes-full01-journal-operation")
                derived, start, end = transport._node_stats(row, nodes, previous, upper)
        rows.append({"raw": row, "started_nanos": str(start), "finished_nanos": str(end), **derived})
        previous = end
    require(owner == suite["owner"], "kubernetes-full01-journal-owner")
    return {"rows": rows, "bytes": str(len(data)), "sha256": sha256(data), "contains_original_failure": True}
