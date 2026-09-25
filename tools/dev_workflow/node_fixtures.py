"""Explicit, byte-bound fixture selection for stopped disposable Linux nodes."""
from __future__ import annotations

from pathlib import Path
import re
import tempfile

from . import paths, process
from .common import decode, digest, encode, members, require


def validate(value: dict) -> dict:
    members(value, set(), {"clock", "http"})
    require(value and len(encode(value)) <= 256 * 1024, "node-fixture-byte-limit")
    if "clock" in value:
        clock = members(value["clock"], {"monotonicNanos", "wallUnixMillis"})
        require(all(isinstance(reading, str) and re.fullmatch(r"0|[1-9][0-9]{0,19}", reading)
                    and int(reading) <= 18446744073709551615 for reading in clock.values()),
                "invalid-guest-clock-fixture")
    if "http" in value:
        from . import http_fixture
        http_fixture.validate(value["http"])
    return value


def configuration(value: dict) -> dict:
    return {"formatVersion": 1, "consent": True, "purpose": "disposable-development-tests",
            "guestClock": dict(validate(value)["clock"])}


def check_configuration(root: Path, value: dict) -> dict:
    from tools.native_runtime import checks
    from tools.native_runtime.layout import Layout
    current = checks.current(Layout.local(root / "runtime"))
    # Validate the installed binary against a private proposed configuration
    # before replacing the node's selected config. Ordinary binaries reject it.
    with tempfile.TemporaryDirectory(prefix=".fixture-check-", dir=root) as temporary:
        selected = Path(temporary) / "node.json"
        paths.write_new(selected, encode(value))
        result = process.run([str(current / "bin/latentd"), "check-config", "--config", str(selected)],
                             root, timeout=45, maximum=65536)
    require(result.returncode == 0, "node-does-not-support-selected-development-fixture")
    report = decode(result.stdout, 65536)
    require(report.get("schemaVersion") == "latent.standalone.config-check.v1"
            and report.get("profile") == "local-experimental-v1"
            and report.get("protectedCredentialFile") is True
            and report.get("developmentGuestClock") == value.get("developmentTest", {}).get("guestClock"),
            "node-development-fixture-not-confirmed")
    return {"configurationSha256": digest(encode(value)),
            "guestClock": report.get("developmentGuestClock"), "ordinaryNodeClock": "unchanged"}


def initialized(source: Path, cases: list[dict], selected: dict | None, runtime: dict | None = None) -> set[str]:
    result = set()
    for case in cases:
        for fixture in case["fixtures"]:
            if fixture["kind"] not in {"test-adapter", "controlled-peer"} or "configuration" not in fixture:
                continue
            raw = paths.read(source, fixture["configuration"], 256 * 1024)
            require(digest(raw) == fixture["identity"], "node-fixture-identity")
            requested = decode(raw, 256 * 1024)
            # Other adapter fixtures remain explicitly unsupported by the
            # common runner until a node implementation has initialized them.
            if not isinstance(requested, dict) or set(requested) not in ({"clock"}, {"http"}):
                continue
            validate(requested)
            if selected is None or any(selected.get(key) != value for key, value in requested.items()):
                continue
            if "clock" in requested and fixture["kind"] == "test-adapter":
                result.add(fixture["id"])
            if "http" in requested and fixture["kind"] == "controlled-peer":
                actual = (runtime or {}).get("http", {})
                if (actual.get("state") == "ready" and actual.get("kind") == "controlled-peer"
                        and actual.get("authentication") == "private-provider-credential"
                        and actual.get("configurationSha256") == digest(encode(requested["http"]))
                        and actual.get("failure") is None):
                    result.add(fixture["id"])
    return result
