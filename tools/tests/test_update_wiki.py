from __future__ import annotations

import importlib.util
import json
from pathlib import Path, PurePosixPath
import tempfile
import unittest
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "update_wiki.py"
SPEC = importlib.util.spec_from_file_location("update_wiki", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
wiki = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(wiki)


def write_valid_source(root: Path) -> None:
    assets = root / "assets"
    assets.mkdir(parents=True)
    marker = wiki.MANAGED_MARKER
    (root / "Home.md").write_text(
        f"{marker}\n# Home\n\n![Flow](assets/flow.svg)\n", encoding="utf-8"
    )
    (root / "_Sidebar.md").write_text(f"{marker}\n# Navigation\n", encoding="utf-8")
    (root / "_Footer.md").write_text(f"{marker}\n# Footer\n", encoding="utf-8")
    (root / "Phase-0-Status.md").write_text(f"{marker}\n# Status\n", encoding="utf-8")
    (assets / "flow.svg").write_text(
        '<svg viewBox="0 0 1 1" role="img"><title>flow</title></svg>', encoding="utf-8"
    )


class WikiPublisherTests(unittest.TestCase):
    def test_checked_in_wiki_source_validates(self) -> None:
        source = Path(__file__).resolve().parents[2] / "wiki" / "pages"
        files = wiki.validate_source(source)
        self.assertEqual(wiki.validate_phase0_status_alignment(source), "blocked")
        self.assertEqual(len(files), 24)
        self.assertIn(PurePosixPath("assets/phase0-activation-flow.svg"), files)
        self.assertIn(PurePosixPath("assets/phase0-evidence-gate.svg"), files)
        self.assertIn(PurePosixPath("assets/roadmap-phases.svg"), files)

    def test_safe_relative_path_rejects_unsafe_paths(self) -> None:
        for value in ("", "../outside.md", "..\\outside.md", "/absolute.md", "C:/outside.md", ".git/config"):
            with self.subTest(value=value):
                with self.assertRaises(wiki.WikiError):
                    wiki._safe_relative_path(value)

    def test_remote_rejects_embedded_credentials(self) -> None:
        https_remote = "https://github.com/owner/repository.wiki.git"
        ssh_remote = "git@github.com:owner/repository.wiki.git"
        self.assertEqual(wiki._validated_remote(https_remote), https_remote)
        self.assertEqual(wiki._validated_remote(ssh_remote), ssh_remote)
        with self.assertRaisesRegex(wiki.WikiError, "embedded Wiki credentials"):
            wiki._validated_remote("https://token@example.invalid/owner/repository.wiki.git")
        with self.assertRaisesRegex(wiki.WikiError, "GitHub Wiki HTTPS or SSH"):
            wiki._validated_remote("file:///tmp/latent-service-fabric.wiki.git")

    def test_supplied_wiki_checkout_must_match_the_selected_remote(self) -> None:
        expected = "https://github.com/owner/repository.wiki.git"
        with patch.object(wiki, "_run", return_value=expected + "\n"):
            wiki._assert_wiki_remote(Path("/tmp/wiki"), expected)
        with patch.object(wiki, "_run", return_value="git@github.com:other/wiki.wiki.git\n"):
            with self.assertRaisesRegex(wiki.WikiError, "does not match"):
                wiki._assert_wiki_remote(Path("/tmp/wiki"), expected)

    def test_validate_source_rejects_mermaid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source"
            write_valid_source(source)
            self.assertEqual(len(wiki.validate_source(source)), 5)
            (source / "Home.md").write_text(
                f"{wiki.MANAGED_MARKER}\n```mermaid\ngraph TD\n```\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(wiki.WikiError, "Mermaid"):
                wiki.validate_source(source)

    def test_synchronize_replaces_only_known_managed_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            destination = root / "wiki"
            destination.mkdir()
            write_valid_source(source)
            (destination / "Home.md").write_text("old home\n", encoding="utf-8")
            (destination / "Old-Managed.md").write_text("old managed\n", encoding="utf-8")
            (destination / "Custom-Page.md").write_text("keep me\n", encoding="utf-8")
            assets = destination / "assets"
            assets.mkdir()
            (assets / "old.svg").write_text("old asset\n", encoding="utf-8")

            written, removed = wiki.synchronize(
                source,
                destination,
                {PurePosixPath("Old-Managed.md"), PurePosixPath("assets/old.svg")},
                "a" * 40,
            )

            self.assertIn(PurePosixPath("Home.md"), written)
            self.assertEqual(
                set(removed), {PurePosixPath("Old-Managed.md"), PurePosixPath("assets/old.svg")}
            )
            self.assertFalse((destination / "Old-Managed.md").exists())
            self.assertFalse((destination / "assets" / "old.svg").exists())
            self.assertEqual((destination / "Custom-Page.md").read_text(encoding="utf-8"), "keep me\n")
            manifest = json.loads((destination / wiki.MANIFEST_NAME).read_text(encoding="utf-8"))
            self.assertEqual(manifest["source_revision"], "a" * 40)
            self.assertIn("Home.md", manifest["managed_files"])
            self.assertIn("assets/flow.svg", manifest["managed_files"])

    def test_synchronize_rejects_a_symlinked_wiki_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            destination = root / "wiki"
            outside = root / "outside"
            destination.mkdir()
            outside.mkdir()
            write_valid_source(source)
            (destination / "assets").symlink_to(outside, target_is_directory=True)

            with self.assertRaisesRegex(wiki.WikiError, "traverses a symlink"):
                wiki.synchronize(source, destination, set(), "a" * 40)


if __name__ == "__main__":
    unittest.main()
