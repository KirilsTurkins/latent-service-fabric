"""Operator-only GitHub security-settings inventory; never supply its token to CI."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.security_common import SecurityError, decode_json, require

REPOSITORY = "KirilsTurkins/latent-service-fabric"


def request(endpoint: str, method: str = "GET", payload: dict | None = None) -> tuple[int, object]:
    command = ["gh", "api", "--include", "--method", method, f"repos/{REPOSITORY}/{endpoint}".rstrip("/")]
    if payload is not None:
        command.extend(["--input", "-"])
    process = subprocess.run(command, input=json.dumps(payload).encode() if payload is not None else None,
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=30, check=False)
    require(len(process.stdout) <= 1024 * 1024, "settings-response-size")
    response = process.stdout.replace(b"\r\n", b"\n")
    headers, separator, body = response.partition(b"\n\n")
    require(bool(separator) and headers.startswith(b"HTTP/"), "settings-api-unavailable")
    status = int(headers.splitlines()[0].split()[1])
    return status, decode_json(body) if body.strip() else None


def require_success(endpoint: str, method: str = "GET", payload: dict | None = None) -> object:
    status, document = request(endpoint, method, payload)
    require(status in {200, 201, 202, 204}, "settings-api-permission-or-service-failure")
    return document


def settings(enable: bool = False) -> dict:
    repository = require_success("")
    require(repository.get("permissions", {}).get("admin") is True, "settings-verification-needs-operator-admin")
    if enable:
        require_success("vulnerability-alerts", "PUT")
        require_success("automated-security-fixes", "PUT")
        require_success("private-vulnerability-reporting", "PUT")
        require_success("", "PATCH", {"security_and_analysis": {
            "secret_scanning": {"status": "enabled"},
            "secret_scanning_push_protection": {"status": "enabled"},
        }})
        repository = require_success("")
    alerts, unused = request("vulnerability-alerts")
    require(alerts in {204, 404}, "vulnerability-alert-state-unavailable")
    updates = require_success("automated-security-fixes")
    disclosure = require_success("private-vulnerability-reporting")
    scanning = require_success("code-scanning/default-setup")
    workflow_permissions = require_success("actions/permissions/workflow")
    default = repository["default_branch"]
    active, unused = request(f"contents/.github/workflows/security-baseline.yml?ref={default}")
    require(active in {200, 404}, "scheduled-definition-state-unavailable")
    protection = require_success("branches/development/protection/required_status_checks")
    services = repository["security_and_analysis"]
    enabled = (alerts == 204 and updates.get("enabled") is True and updates.get("paused") is False
               and disclosure.get("enabled") is True
               and services.get("secret_scanning", {}).get("status") == "enabled"
               and services.get("secret_scanning_push_protection", {}).get("status") == "enabled")
    return {"schema": 1, "repository": REPOSITORY, "observed_at": datetime.now(timezone.utc).isoformat(),
            "settings_enabled": enabled, "default_branch": default, "vulnerability_alerts": alerts == 204,
            "security_and_analysis": services, "dependabot_security_updates": updates,
            "private_vulnerability_reporting": disclosure, "code_scanning_default_setup": scanning,
            "workflow_permissions": workflow_permissions, "scheduled_definition_on_default": active == 200,
            "development_required_checks": protection.get("contexts", []),
            "auto_merge_capability": repository["allow_auto_merge"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--enable", action="store_true", help="Explicitly enable supported monitoring/protection settings")
    arguments = parser.parse_args()
    try:
        report = settings(arguments.enable)
        print(json.dumps(report, sort_keys=True, separators=(",", ":")))
        return 0 if report["settings_enabled"] else 1
    except (SecurityError, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        code = str(error) if isinstance(error, SecurityError) else "repository-settings-unavailable"
        print(json.dumps({"schema": 1, "status": "error", "code": code}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
