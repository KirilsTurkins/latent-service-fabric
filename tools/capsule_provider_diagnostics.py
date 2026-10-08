"""Private bounded observations before a failed provider wait cleans its owner."""
from __future__ import annotations

import base64
import hashlib
import json
import stat

from tools.phase2_operator_process import require, write_json
from tools.phase2_operator_scenario import NODE_ID

MAX_BYTES = 262144
MAX_PROCESS_BYTES = 32768
MAX_PEER_BYTES = 4096
KINDS = ("deadline", "cancel", "disconnect")
CODES = (0, 2, 3, 4, 5, 6, 130)


def marker(control, name):
    """Read only fixed owned fixture paths, with finite size and no links."""
    path = control / name
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return {"present": False}
    require(stat.S_ISREG(metadata.st_mode) and metadata.st_size <= 32,
            "authoring-provider-diagnostic-marker")
    with path.open("rb") as source:
        raw = source.read(33)
    require(len(raw) <= 32, "authoring-provider-diagnostic-marker")
    return {"present": True, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "observed": raw == b"observed\n"}


def process_snapshot(process, maximum):
    # Nonblocking reads only. Do not finish, poll/reap or signal a process to
    # obtain diagnostics. The existing outer finally retains cleanup ownership.
    for _ in range(3):
        process.drain()
    raw = tuple(bytes(value) for value in process.buffers)
    require(sum(map(len, raw)) <= maximum, "authoring-provider-diagnostic-process-bound")
    return {
        "stdoutBase64": base64.b64encode(raw[0]).decode("ascii"),
        "stderrBase64": base64.b64encode(raw[1]).decode("ascii"),
        "pipesClosed": not any(process.streams), "closed": process.closed,
        "leaderExitObserved": process.owner.exited(),
        "processReaped": process.owner.finished,
        "exitCode": process.owner.process.returncode,
    }


def capture(client, process, control, name, *, peer=None):
    """Retain the failed attempt without waiting, retrying or changing its outcome.

    Raw stdout/stderr belongs to this fixed public-input test and remains in its
    private evidence directory. All management reads use the original operator,
    deadline, cancellation, control-count and output limits. A missing marker,
    observed process exit or cleanup does not establish an activation outcome.
    """
    diagnostics = {"schemaVersion": "latent.authoring-provider-diagnostic.v1",
                   "outcomeInferred": False, "management": {}, "markers": {}}
    try:
        require(name in tuple("started-hold-" + kind for kind in KINDS),
                "authoring-provider-diagnostic-name")
        activation = process.authoring_activation
        require(activation in tuple("authoring-" + kind for kind in KINDS),
                "authoring-provider-diagnostic-activation")
        diagnostics.update(activation=activation, expectedMarker=name,
                           startedAtUnixMillis=str(process.authoring_started_unix_millis))
        diagnostics["invocation"] = process_snapshot(process, MAX_PROCESS_BYTES)
        if peer is not None:
            diagnostics["peer"] = process_snapshot(peer, MAX_PEER_BYTES)
        for kind in KINDS:
            for prefix in ("started-hold-", "closed-hold-"):
                selected = prefix + kind
                diagnostics["markers"][selected] = marker(control, selected)
        mode = control / "mode"
        metadata = mode.lstat()
        require(stat.S_ISREG(metadata.st_mode) and metadata.st_size <= 32,
                "authoring-provider-diagnostic-mode")
        with mode.open("rb") as source:
            raw_mode = source.read(33)
        require(raw_mode in (b"reply", b"hold-deadline", b"hold-cancel", b"hold-disconnect"),
                "authoring-provider-diagnostic-mode")
        diagnostics["mode"] = raw_mode.decode("ascii")
        commands = (
            ("activation", ("activation", "get", activation)),
            ("tree", ("activation", "tree", activation, "--page-size", "128")),
            ("node", ("node", "get", NODE_ID)),
            ("providers", ("capability", "list", "--page-size", "128")),
        )
        for selected, command in commands:
            value = client._control_call(*command, codes=CODES)
            require(len(json.dumps(diagnostics).encode()) + len(json.dumps(value).encode()) <= MAX_BYTES,
                    "authoring-provider-diagnostic-retention")
            diagnostics["management"][selected] = value
    except Exception as error:
        # A failed observation never replaces the original assertion. Exception
        # text, argv, input, credentials and environment are deliberately absent.
        diagnostics["diagnosticFailure"] = type(error).__name__
    try:
        encoded = json.dumps(diagnostics).encode()
        require(len(encoded) <= MAX_BYTES, "authoring-provider-diagnostic-retention")
        require(client.retained + len(encoded) <= 4 * 1024 * 1024,
                "authoring-control-retention")
        client.retained += len(encoded)
        write_json(client.evidence / "provider-rendezvous-failure.json", diagnostics)
    except Exception:
        pass
