"""Bounded Linux socket observations; absence is never a retirement certificate."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.owned_test_process import ProcessFailure, run_owned

STATES = frozenset(("ESTAB", "FIN-WAIT-1", "FIN-WAIT-2", "TIME-WAIT", "CLOSE-WAIT", "LAST-ACK", "CLOSING", "CLOSE", "SYN-SENT", "SYN-RECV"))
MEMORY = {"r": "receiveAllocatedBytes", "rb": "receiveLimitBytes", "t": "transmitAllocatedBytes", "tb": "transmitLimitBytes", "f": "forwardAllocatedBytes", "w": "queuedWriteBytes", "o": "optionBytes", "bl": "backlogBytes", "d": "drops"}
MAXIMUM = 16384


def parse(raw: bytes, inode: int) -> dict:
    if type(inode) is not int or not 0 < inode < 2**64 or len(raw) > MAXIMUM:
        raise ValueError("kernel-observer-bound")
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError:
        raise ValueError("kernel-observer-encoding") from None
    lines = text.splitlines()
    if len(lines) > 1 or any(len(line) > 8192 for line in lines):
        raise ValueError("kernel-observer-row-count")
    result = {"matchingRows": len(lines), "state": "absent", "inodeMatched": False, "memory": None, "retirementProven": False}
    if not lines:
        return result
    line = lines[0]
    fields = line.split()
    if len(fields) < 5 or fields[0] not in STATES:
        raise ValueError("kernel-observer-state")
    result["state"] = fields[0]
    found = re.findall(r"(?:^|\s)ino:([0-9]{1,20})(?:\s|$)", line)
    if len(found) != 1 or int(found[0]) not in (0, inode):
        raise ValueError("kernel-observer-inode")
    result["inodeMatched"] = int(found[0]) == inode
    matched = re.findall(r"(?:^|\s)skmem:\(([^()]*)\)(?:\s|$)", line)
    if len(matched) > 1:
        raise ValueError("kernel-observer-memory-count")
    if matched:
        values = {}
        for value in matched[0].split(","):
            pair = re.fullmatch(r"([a-z]{1,2})([0-9]{1,10})", value)
            if pair is None or pair[1] not in MEMORY or pair[1] in values or int(pair[2]) > 2**32 - 1:
                raise ValueError("kernel-observer-memory-field")
            values[pair[1]] = int(pair[2])
        if set(values) != set(MEMORY):
            raise ValueError("kernel-observer-memory-fields")
        result["memory"] = {MEMORY[key]: value for key, value in values.items()}
    return result


def validate_projection(value: dict) -> None:
    if (type(value) is not dict or set(value) != {"matchingRows", "state", "inodeMatched", "memory", "retirementProven", "toolSha256"}
            or type(value["matchingRows"]) is not int or value["matchingRows"] not in (0, 1)
            or type(value["inodeMatched"]) is not bool or value["retirementProven"] is not False
            or type(value["toolSha256"]) is not str or not re.fullmatch(r"[a-f0-9]{64}", value["toolSha256"])):
        raise ValueError("kernel-observer-projection")
    if value["matchingRows"] == 0:
        if value["state"] != "absent" or value["inodeMatched"] or value["memory"] is not None:
            raise ValueError("kernel-observer-absent-shape")
    elif value["state"] not in STATES:
        raise ValueError("kernel-observer-state")
    memory = value["memory"]
    if memory is not None and (type(memory) is not dict or set(memory) != set(MEMORY.values())
            or any(type(n) is not int or not 0 <= n <= 2**32 - 1 for n in memory.values())):
        raise ValueError("kernel-observer-memory-projection")


def observe(local_port: int, peer_port: int, inode: int) -> dict:
    if (sys.platform != "linux" or type(inode) is not int or not 0 < inode < 2**64
            or any(type(port) is not int or not 0 < port < 65536 for port in (local_port, peer_port))):
        raise ValueError("kernel-observer-platform-or-port")
    executable = Path("/usr/bin/ss")
    if executable.is_symlink():
        executable = executable.resolve(strict=True)
    if not executable.is_file() or not 0 < executable.stat().st_size <= 16 * 1024 * 1024:
        raise ValueError("kernel-observer-tool")
    tool_before = hashlib.sha256(executable.read_bytes()).hexdigest()
    query = f"src 127.0.0.1 and sport = :{local_port} and dst 127.0.0.1 and dport = :{peer_port}"
    captured = run_owned([str(executable), "-tanmeO", "--no-header", query], cwd=Path.cwd(), timeout=2, maximum=MAXIMUM, separate_stderr=True)
    if captured.returncode or captured.stderr:
        raise ValueError("kernel-observer-command")
    if hashlib.sha256(executable.read_bytes()).hexdigest() != tool_before:
        raise ValueError("kernel-observer-tool-changed")
    result = parse(captured.output, inode)
    result["toolSha256"] = tool_before
    validate_projection(result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-port", type=int, required=True)
    parser.add_argument("--peer-port", type=int, required=True)
    parser.add_argument("--inode", type=int, required=True)
    args = parser.parse_args()
    try:
        result = observe(args.local_port, args.peer_port, args.inode)
    except (ValueError, OSError, ProcessFailure):
        print("kernel-observation-unavailable", file=sys.stderr)
        return 1
    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
