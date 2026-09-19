from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import xml.etree.ElementTree as ElementTree

SPEC = importlib.util.spec_from_file_location("illustration_palette", Path(__file__).resolve().parents[1] / "illustration_palette.py")
assert SPEC is not None and SPEC.loader is not None
palette_tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(palette_tool)


class IllustrationPaletteTests(unittest.TestCase):
    def test_current_inventory_covers_every_svg_and_preserves_exact_originals(self) -> None:
        inventory, palette, outputs = palette_tool.prepare()
        self.assertEqual(len(inventory["sources"]), 5)
        self.assertEqual(len(outputs), 2)
        for relative, expected in outputs:
            self.assertEqual(palette_tool.read_bytes(palette_tool.ROOT, relative), expected)
            entry = next(entry for entry in inventory["outputs"] if entry["path"] == relative)
            original = palette_tool.read_bytes(palette_tool.ROOT, entry["source"])
            self.assertEqual(palette_tool.COLOR.sub("COLOR", expected.decode()), palette_tool.COLOR.sub("COLOR", original.decode()))
            original_svg = ElementTree.fromstring(original)
            presented_svg = ElementTree.fromstring(expected)
            self.assertEqual(original_svg.attrib, presented_svg.attrib)
            for before, after in zip(original_svg.iter(), presented_svg.iter(), strict=True):
                self.assertEqual(before.tag, after.tag)
                if not before.tag.endswith("style"):
                    self.assertEqual(before.text, after.text)
                self.assertEqual(before.tail, after.tail)
                for attribute in ("id", "viewBox", "role", "aria-labelledby", "d", "x", "y", "marker-end", "orient"):
                    self.assertEqual(before.get(attribute), after.get(attribute))

    def test_generation_is_deterministic_and_changes_only_new_presentations(self) -> None:
        inventory, palette, outputs = palette_tool.prepare()
        original_hashes = {entry["path"]: hashlib.sha256(palette_tool.read_bytes(palette_tool.ROOT, entry["path"])).hexdigest() for entry in inventory["sources"]}
        changed = dict(palette["modes"]["dark"], link="#FFE4A3")
        for entry, (_, expected) in zip(inventory["outputs"], outputs, strict=True):
            source = palette_tool.read_bytes(palette_tool.ROOT, entry["source"])
            self.assertEqual(palette_tool.render(source, inventory["replacements"], palette["modes"]["dark"]), expected)
            self.assertNotEqual(palette_tool.render(source, inventory["replacements"], changed), expected)
        self.assertEqual(original_hashes, {entry["path"]: hashlib.sha256(palette_tool.read_bytes(palette_tool.ROOT, entry["path"])).hexdigest() for entry in inventory["sources"]})

    def test_unknown_colors_missing_inventory_and_historical_drift_fail(self) -> None:
        with self.assertRaisesRegex(ValueError, "unreviewed source colors"):
            palette_tool.render(b'<rect fill="#123456"/>', {}, {})
        with self.assertRaisesRegex(ValueError, "unknown semantic"):
            palette_tool.render(b'<rect fill="#123456"/>', {"#123456": "missing"}, {})
        original_git = palette_tool.git
        with patch.object(palette_tool, "git", side_effect=lambda *arguments: original_git(*arguments) + "\0website/static/brand/unreviewed.SvG"):
            with self.assertRaisesRegex(ValueError, "missing an explicit disposition"):
                palette_tool.prepare()
        original_read = palette_tool.read_bytes
        def altered_read(root: Path, relative: str) -> bytes:
            content = original_read(root, relative)
            return content + b"\n" if relative == "docs/assets/phase0-gate-decision.svg" else content
        with patch.object(palette_tool, "read_bytes", side_effect=altered_read):
            with self.assertRaisesRegex(ValueError, "historical bytes changed"):
                palette_tool.prepare()

    def test_paths_duplicates_and_limits_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for unsafe in ("../escape.svg", "/absolute.svg", "docs\\asset.svg", "docs//asset.svg"):
                with self.assertRaises(ValueError):
                    palette_tool.safe_path(root, unsafe)
            source = root / "oversized.svg"
            source.write_bytes(b"x" * (palette_tool.MAX_BYTES + 1))
            with self.assertRaisesRegex(ValueError, "oversized"):
                palette_tool.read_bytes(root, source.name)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            json.loads('{"schema":1,"schema":2}', object_pairs_hook=palette_tool.unique_object)
        self.assertEqual(palette_tool.contrast("#000000", "#FFFFFF"), 21)


if __name__ == "__main__":
    unittest.main()
