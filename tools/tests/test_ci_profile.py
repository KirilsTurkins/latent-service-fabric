from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools import ci_profile as profile


class ClassificationTests(unittest.TestCase):
    def test_website_sources_use_only_the_site_and_documentation_jobs(self) -> None:
        for path in ("website/package-lock.json", "website/docusaurus.config.ts", "website/src/pages/index.tsx",
                     "website/plugins/examples/remark.mjs", "website/src/css/theme.css", "website/content/coverage.json",
                     "docs/learn/first.mdx", "adr/design.mdx", "docs/assets/lsf-palette.json"):
            with self.subTest(path=path):
                result = profile.classify_paths(["README.md", path])
                self.assertEqual(result.profile, "website")
                self.assertFalse(result.renderer)
        for path in ("website/../Cargo.toml", "website//config.json", "website/new.py",
                     "website/build/index.js", "website/.generated/evidence.json", "website/.docusaurus/data.json",
                     "website/node_modules/package/index.js", "tools/ci_result.py", "sdk/go/client.go",
                     "examples/website-ui/specimen.rs", "benchmarks/receipt.json", "wit/platform/web/world.wit"):
            with self.subTest(path=path):
                self.assertEqual(profile.classify_paths(["website/src/pages/index.tsx", path]).profile, "full")

    def test_renderer_proof_follows_its_inputs_and_defaults_to_running(self) -> None:
        for path in ["Cargo.lock", "Cargo.toml", "tools/renderer-profile/src/main.rs",
                     "examples/renderer-profile/package-lock.json",
                     "crates/latent-wasmtime/src/backend.rs", ".github/workflows/ci.yml",
                     "wit/platform/web/package.wit", "tools/ci_profile.py"]:
            with self.subTest(path=path):
                self.assertTrue(profile.classify_paths(["README.md", path]).renderer)
        for path in ["tools/angular-renderer-adapter/src/lib.rs", "tools/build_angular_renderer.py",
                     "tools/angular_build/guard.mjs", "tools/build_angular_package.py",
                     "tools/run_angular_build_tests.py", "tools/check_angular_hydration.mjs",
                     "examples/angular-application/server/main.ts", "tools/build_inventory_units.py",
                     "crates/latent-signing/src/web_provenance/angular.rs", "crates/latent-policy/src/supply_chain.rs",
                     "apps/latent/src/package.rs", "schemas/angular-build.schema.json",
                     "schemas/web-build-observation.schema.json", "schemas/builder-policy.schema.json",
                     "tools/tests/test_build_angular_package.py", "tools/tests/test_angular_build_runner.py",
                     "tools/run_angular_renderer_tests.py", "apps/latentd/src/config/renderer.rs",
                     "crates/latent-packaging/src/semantics/web.rs", "crates/latent-manifest/src/renderer.rs",
                     "crates/latent-node/src/lib.rs", "crates/latent-ingress/src/http.rs"]:
            with self.subTest(path=path):
                self.assertTrue(profile.classify_paths([path]).renderer)
        for path in ["examples/browser-boundary/shared/hydration.ts", "tools/browser-boundary/build.mjs",
                     "tools/browser-boundary/browser.mjs", "tools/tests/browser_hydration.test.mjs"]:
            with self.subTest(path=path):
                self.assertTrue(profile.classify_paths([path]).renderer)
        self.assertFalse(profile.classify_paths(["README.md"]).renderer)
        self.assertFalse(profile.classify_paths(["sdk/go/client.go"]).renderer)
        self.assertTrue(profile.classify_paths([]).renderer)
        self.assertTrue(profile.classify_event("workflow_dispatch", {}, Path.cwd()).renderer)
        self.assertTrue(profile.classify_event("push", {}, Path.cwd()).renderer)

    def test_only_known_documentation_is_allowlisted(self) -> None:
        allowed = [
            "README.md", "ARCHITECTURE.md", "CONTRIBUTING.md", "VALIDATION.md", "docs/roadmap.md",
            "docs/reference/operator-cli.md", "docs/assets/boundary.svg",
            "adr/0021-decision.md", "research/future/plan.md", "rfcs/next.md",
            "crates/latent-core/README.md", "sdk/python-client/README.md",
            "examples/package-inputs/README.md", "schemas/README.md",
        ]
        self.assertEqual(profile.classify_paths(allowed).profile, "docs")
        denied = [
            "new-root-file.md", "docs/assets/code.js", "docs/config.json",
            "docs/testing/phase-2-resource-profile.md", "benchmarks/README.md",
            "benchmarks/phase2/receipt.json", "examples/package-inputs/template.md",
            "schemas/capsule.schema.json", "crates/latent-core/src/lib.rs",
            "sdk/python-client/client.py", "Cargo.lock", "Cargo.toml",
            ".github/workflows/ci.yml", "tools/ci_profile.py", "tools/toolchain.toml",
            ".github/ISSUE_TEMPLATE/bug_report.yml", "docs/../Cargo.toml",
            "/docs/roadmap.md", "docs//roadmap.md", "docs\\roadmap.md",
            "docs/line\nbreak.md", "docs/./roadmap.md",
        ]
        for name in denied:
            with self.subTest(name=name):
                self.assertEqual(profile.classify_paths(["README.md", name]).profile, "full")

    def test_code_after_three_hundred_documentation_paths_is_not_truncated(self) -> None:
        names = [f"docs/page-{index}.md" for index in range(400)] + ["src/last.rs"]
        result = profile.classify_paths(names)
        self.assertEqual((result.profile, result.changed_files), ("full", 401))
        decoded = profile.diff_paths(b"\0".join(name.encode() for name in names) + b"\0")
        self.assertEqual(decoded, names)

    def test_empty_and_oversized_inputs_never_select_docs(self) -> None:
        self.assertEqual(profile.classify_paths([]).profile, "full")
        with patch.object(profile, "MAX_PATHS", 2):
            self.assertEqual(profile.classify_paths(["README.md"] * 3).profile, "full")
            with self.assertRaises(profile.ProfileError):
                profile.diff_paths(b"README.md\0README.md\0README.md\0")
        self.assertFalse(profile.documentation_path("docs/" + "a" * 4096 + ".md"))

    def test_malformed_diff_and_event_bytes_are_rejected(self) -> None:
        for value in (b"README.md", b"README.md\0\0", b"docs/\xff.md\0"):
            with self.subTest(value=value), self.assertRaises(profile.ProfileError):
                profile.diff_paths(value)
        with tempfile.TemporaryDirectory() as temporary:
            event = Path(temporary) / "event.json"
            for value in (b'{"before":1,"before":2}', b"[]", b"{", b"x" * (profile.MAX_EVENT_BYTES + 1)):
                event.write_bytes(value)
                with self.subTest(value=value[:30]), self.assertRaises((profile.ProfileError, ValueError)):
                    profile.read_event(event)

    def test_dispatch_unknown_and_missing_push_boundaries_require_full_without_git(self) -> None:
        with patch.object(profile, "git_command") as git:
            for name, event in (
                ("workflow_dispatch", {}), ("merge_group", {}), ("push", {}),
                ("push", {"before": "0" * 40, "after": "a" * 40}),
            ):
                self.assertEqual(profile.classify_event(name, event, Path.cwd()).profile, "full")
            git.assert_not_called()

    def test_invalid_identities_are_not_git_arguments(self) -> None:
        with patch.object(profile, "git_command") as git:
            for value in ("--upload-pack=evil", "a" * 39, "g" * 40, 123, None):
                event = {"pull_request": {"base": {"sha": value}, "head": {"sha": "a" * 40}}}
                with self.subTest(value=value), self.assertRaises(profile.ProfileError):
                    profile.classify_event("pull_request", event, Path.cwd())
            git.assert_not_called()

    def test_missing_history_is_bounded_and_selects_full(self) -> None:
        event = {"pull_request": {"base": {"sha": "a" * 40}, "head": {"sha": "b" * 40}}}
        with patch.object(profile, "git_command", return_value=None) as git:
            result = profile.classify_event("pull_request", event, Path.cwd())
        self.assertEqual((result.profile, result.reason), ("full", "history-unavailable"))
        fetches = [call.args[1:] for call in git.call_args_list if call.args[1] == "fetch"]
        self.assertEqual(fetches, [
            ("fetch", "--no-tags", "--filter=blob:none", "--depth=128", "origin", "a" * 40, "b" * 40),
            ("fetch", "--no-tags", "--filter=blob:none", "--depth=512", "origin", "a" * 40, "b" * 40),
        ])

    def test_failure_never_emits_docs_or_any_accepted_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            event, output = root / "event.json", root / "output"
            event.write_text(json.dumps({"before": "a" * 40, "after": "b" * 40}), encoding="utf-8")
            args = ["--event-name", "push", "--event-path", str(event), "--github-output", str(output)]
            with patch.dict(os.environ, {}, clear=True), patch.object(
                profile, "git_command", side_effect=profile.ProfileError("git-command-failed")
            ), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(profile.main(args), 1)
            self.assertFalse(output.exists())

    def test_output_uses_only_fixed_profile_reason_and_count(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            event, output, summary = root / "event.json", root / "output", root / "summary"
            event.write_text("{}", encoding="utf-8")
            args = ["--event-name", "workflow_dispatch", "--event-path", str(event),
                    "--github-output", str(output), "--github-step-summary", str(summary)]
            with patch.dict(os.environ, {}, clear=True), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(profile.main(args), 0)
            self.assertEqual(output.read_text(), "profile=full\nreason=manual-dispatch\nchanged_files=0\nrenderer=true\n")
            self.assertIn("manual-dispatch", summary.read_text())


class GitHistoryTests(unittest.TestCase):
    """Small real graphs catch diff direction, rename and shallow-history mistakes."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.repo = Path(self.temporary.name)
        self.git("init", "--quiet")
        self.git("config", "user.email", "ci-profile@example.invalid")
        self.git("config", "user.name", "CI profile test")
        self.write("README.md", "base\n")
        self.base = self.commit()

    def git(self, *arguments: str) -> str:
        result = subprocess.run(
            ["git", "-c", "gc.auto=0", *arguments], cwd=self.repo,
            check=True, capture_output=True, text=True, timeout=15,
        )
        return result.stdout.strip()

    def write(self, path: str, content: str) -> None:
        target = self.repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def commit(self) -> str:
        self.git("add", "--all")
        self.git("commit", "--quiet", "-m", "fixture")
        return self.git("rev-parse", "HEAD")

    def pr(self, base: str, head: str) -> profile.Decision:
        return profile.classify_event("pull_request", {
            "pull_request": {"base": {"sha": base}, "head": {"sha": head}},
        }, self.repo)

    def test_pr_uses_merge_base_and_excludes_unrelated_base_changes(self) -> None:
        self.write("docs/topic.md", "topic\n")
        topic = self.commit()
        self.git("checkout", "--quiet", "--detach", self.base)
        self.write("src/base-only.rs", "fn base_only() {}\n")
        advanced_base = self.commit()
        with patch.object(profile, "git_command", wraps=profile.git_command) as git:
            result = self.pr(advanced_base, topic)
        self.assertEqual((result.profile, result.changed_files), ("docs", 1))
        self.assertFalse(any(call.args[1] == "fetch" for call in git.call_args_list))

    def test_push_covers_every_commit_not_only_head_parent(self) -> None:
        self.write("src/earlier.rs", "fn earlier() {}\n")
        self.commit()
        self.write("docs/latest.md", "docs\n")
        head = self.commit()
        result = profile.classify_event("push", {"before": self.base, "after": head}, self.repo)
        self.assertEqual((result.profile, result.changed_files), ("full", 2))

    def test_rename_from_code_to_documentation_includes_deleted_source(self) -> None:
        self.write("src/original.rs", "same bytes\n")
        base = self.commit()
        (self.repo / "docs").mkdir()
        (self.repo / "src/original.rs").rename(self.repo / "docs/moved.md")
        head = self.commit()
        result = self.pr(base, head)
        self.assertEqual((result.profile, result.changed_files), ("full", 2))

    def test_deleted_documentation_and_frozen_input_are_distinct(self) -> None:
        (self.repo / "README.md").unlink()
        deleted = self.commit()
        self.assertEqual(self.pr(self.base, deleted).profile, "docs")
        self.write("docs/testing/phase-2-resource-profile.md", "changed measurement input\n")
        frozen = self.commit()
        self.assertEqual(self.pr(deleted, frozen).profile, "full")

    def test_executable_markdown_mode_requires_full(self) -> None:
        self.git("update-index", "--chmod=+x", "README.md")
        self.git("commit", "--quiet", "-m", "mode fixture")
        head = self.git("rev-parse", "HEAD")
        result = self.pr(self.base, head)
        self.assertEqual((result.profile, result.reason), ("full", "non-documentation-mode"))

    def test_site_renames_deletions_and_modes_keep_the_complete_inventory(self) -> None:
        self.write("website/src/page.tsx", "export default 1;\n")
        first = self.commit()
        self.assertEqual(self.pr(self.base, first).profile, "website")
        (self.repo / "website/src/page.tsx").rename(self.repo / "website/src/page.mjs")
        renamed = self.commit()
        self.assertEqual(self.pr(first, renamed).changed_files, 2)
        self.assertEqual(self.pr(first, renamed).profile, "website")
        self.git("update-index", "--chmod=+x", "website/src/page.mjs")
        self.git("commit", "--quiet", "-m", "site mode")
        changed_mode = self.git("rev-parse", "HEAD")
        self.assertEqual(self.pr(renamed, changed_mode).profile, "full")
        (self.repo / "website/src/page.mjs").unlink()
        deleted = self.commit()
        self.assertEqual(self.pr(changed_mode, deleted).profile, "full")


    def test_real_diff_collects_more_than_three_hundred_files(self) -> None:
        for index in range(305):
            self.write(f"docs/page-{index}.md", "doc\n")
        self.write("zz/last.rs", "fn last() {}\n")
        head = self.commit()
        result = self.pr(self.base, head)
        self.assertEqual((result.profile, result.changed_files), ("full", 306))

    def test_depth_one_checkout_fetches_exact_missing_history(self) -> None:
        self.git("config", "uploadpack.allowFilter", "true")
        self.write("docs/first.md", "first\n")
        self.commit()
        self.write("docs/last.md", "last\n")
        head = self.commit()
        with tempfile.TemporaryDirectory() as temporary:
            checkout = Path(temporary) / "checkout"
            self.git("clone", "--quiet", "--no-checkout", "--depth=1", "--filter=blob:none",
                     self.repo.as_uri(), str(checkout))
            self.assertFalse(profile.commit_exists(checkout, self.base))
            with patch.object(profile, "git_command", wraps=profile.git_command) as git:
                result = profile.classify_event("pull_request", {
                    "pull_request": {"base": {"sha": self.base}, "head": {"sha": head}},
                }, checkout)
            self.assertEqual((result.profile, result.changed_files), ("docs", 2))
            fetches = [call for call in git.call_args_list if call.args[1] == "fetch"]
            self.assertEqual(len(fetches), 1)


if __name__ == "__main__":
    unittest.main()
