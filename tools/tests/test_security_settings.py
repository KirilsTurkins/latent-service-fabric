from __future__ import annotations

import copy
import unittest
from unittest.mock import patch

from tools.security_common import SecurityError
from tools.security_settings import settings


class SecuritySettingsTests(unittest.TestCase):
    def fixture(self) -> dict:
        return {
            "": {"permissions": {"admin": True}, "default_branch": "release", "allow_auto_merge": True,
                 "security_and_analysis": {"secret_scanning": {"status": "enabled"},
                                           "secret_scanning_push_protection": {"status": "enabled"}}},
            "automated-security-fixes": {"enabled": True, "paused": False},
            "private-vulnerability-reporting": {"enabled": True},
            "code-scanning/default-setup": {"state": "not-configured"},
            "actions/permissions/workflow": {"default_workflow_permissions": "read", "can_approve_pull_request_reviews": False},
            "branches/development/protection/required_status_checks": {"contexts": ["CI result"]},
        }

    def test_enabled_settings_are_separate_from_inactive_schedule_and_required_gate(self) -> None:
        responses = self.fixture()

        def request(endpoint, method="GET", payload=None):
            self.assertEqual(method, "GET")
            if endpoint == "vulnerability-alerts":
                return 204, None
            if endpoint.startswith("contents/"):
                return 404, None
            return 200, responses[endpoint]

        with patch("tools.security_settings.request", side_effect=request):
            report = settings()
        self.assertTrue(report["settings_enabled"])
        self.assertFalse(report["scheduled_definition_on_default"])
        self.assertNotIn("Security baseline result", report["development_required_checks"])
        self.assertEqual(report["code_scanning_default_setup"]["state"], "not-configured")

    def test_disabled_or_unavailable_service_never_becomes_enabled(self) -> None:
        for state in (404, 403, 500):
            responses = self.fixture()

            def request(endpoint, method="GET", payload=None):
                if endpoint == "vulnerability-alerts":
                    return state, None
                if endpoint.startswith("contents/"):
                    return 404, None
                return 200, responses[endpoint]

            with patch("tools.security_settings.request", side_effect=request):
                if state == 404:
                    self.assertFalse(settings()["settings_enabled"])
                else:
                    with self.assertRaises(SecurityError):
                        settings()

    def test_enabling_is_explicit_and_does_not_change_branch_or_merge_policy(self) -> None:
        responses = self.fixture()
        writes = []

        def request(endpoint, method="GET", payload=None):
            if method != "GET":
                writes.append((endpoint, method, copy.deepcopy(payload)))
                return 204, None
            if endpoint == "vulnerability-alerts":
                return 204, None
            if endpoint.startswith("contents/"):
                return 404, None
            return 200, responses[endpoint]

        with patch("tools.security_settings.request", side_effect=request):
            self.assertTrue(settings(enable=True)["settings_enabled"])
        self.assertEqual([entry[0] for entry in writes], ["vulnerability-alerts", "automated-security-fixes",
                                                        "private-vulnerability-reporting", ""])
        self.assertEqual(set(writes[-1][2]), {"security_and_analysis"})


if __name__ == "__main__":
    unittest.main()
