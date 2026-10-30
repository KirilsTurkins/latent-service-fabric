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
            "automated-security-fixes": {"enabled": False, "paused": False},
            "private-vulnerability-reporting": {"enabled": True},
            "code-scanning/default-setup": {"state": "not-configured"},
            "actions/permissions/workflow": {"default_workflow_permissions": "read", "can_approve_pull_request_reviews": False},
            "branches/development/protection/required_status_checks": {"contexts": ["CI result"]},
        }

    def observe(self, responses=None, *, alerts=204, enable=False):
        responses = self.fixture() if responses is None else responses
        writes = []

        def request(endpoint, method="GET", payload=None):
            if method != "GET":
                self.assertTrue(enable)
                writes.append((endpoint, method, copy.deepcopy(payload)))
                return 204, None
            if endpoint == "vulnerability-alerts":
                return alerts, None
            if endpoint.startswith("contents/"):
                return 404, None
            return 200, responses[endpoint]

        with patch("tools.security_settings.request", side_effect=request):
            return settings(enable), writes

    def test_enabled_settings_are_separate_from_inactive_schedule_and_required_gate(self) -> None:
        report, writes = self.observe()
        self.assertEqual(writes, [])
        self.assertTrue(report["settings_enabled"])
        self.assertEqual(report["dependabot_target_branch"], "development")
        self.assertFalse(report["dependabot_security_updates_expected"])
        self.assertTrue(report["dependabot_security_updates_match_policy"])
        self.assertFalse(report["scheduled_definition_on_default"])
        self.assertNotIn("Security baseline result", report["development_required_checks"])
        self.assertEqual(report["code_scanning_default_setup"]["state"], "not-configured")

    def test_disabled_or_unavailable_service_never_becomes_enabled(self) -> None:
        for state in (404, 403, 500):
            with self.subTest(status=state):
                if state == 404:
                    self.assertFalse(self.observe(alerts=state)[0]["settings_enabled"])
                else:
                    with self.assertRaises(SecurityError):
                        self.observe(alerts=state)

    def test_enabling_is_explicit_and_does_not_change_branch_or_merge_policy(self) -> None:
        for default, method in (("release", "DELETE"), ("development", "PUT"), ("main", "DELETE")):
            with self.subTest(default=default):
                responses = self.fixture()
                responses[""]["default_branch"] = default
                responses["automated-security-fixes"]["enabled"] = default == "development"
                report, writes = self.observe(responses, enable=True)
                self.assertTrue(report["settings_enabled"])
                self.assertEqual([entry[0] for entry in writes], ["vulnerability-alerts", "automated-security-fixes",
                                                                "private-vulnerability-reporting", ""])
                self.assertEqual(writes[1], ("automated-security-fixes", method, None))
                self.assertEqual(set(writes[-1][2]), {"security_and_analysis"})

    def test_security_update_state_must_match_the_development_only_policy(self) -> None:
        for default, enabled, paused, compliant in (
            ("release", False, False, True),
            ("release", True, False, False),
            ("main", False, False, True),
            ("main", True, False, False),
            ("development", True, False, True),
            ("development", False, False, False),
            ("development", True, True, False),
        ):
            with self.subTest(default=default, enabled=enabled, paused=paused):
                responses = self.fixture()
                responses[""]["default_branch"] = default
                responses["automated-security-fixes"] = {"enabled": enabled, "paused": paused}

                report, writes = self.observe(responses)
                self.assertEqual(writes, [])
                self.assertEqual(report["settings_enabled"], compliant)
                self.assertEqual(report["dependabot_security_updates_match_policy"], compliant)


if __name__ == "__main__":
    unittest.main()
