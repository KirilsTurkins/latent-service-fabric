from __future__ import annotations

import importlib.util
import re
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STAGER_PATH = ROOT / "tools" / "stage_runtime_wit.py"
SPEC = importlib.util.spec_from_file_location("stage_runtime_wit", STAGER_PATH)
assert SPEC is not None and SPEC.loader is not None
stager = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(stager)

INTERFACE = re.compile(r"^\s*interface\s+([%a-zA-Z][%a-zA-Z0-9-]*)\s*\{")
TYPE_ITEM = re.compile(
    r"^\s*(?:type|record|variant|enum|flags|resource)\s+([%a-zA-Z][%a-zA-Z0-9-]*)\b"
)
FUNCTION_ITEM = re.compile(
    r"^\s*([%a-zA-Z][%a-zA-Z0-9-]*)\s*:\s*(?:async\s+)?func\b"
)


def duplicate_interface_items(text: str) -> list[tuple[str, str, int, int]]:
    duplicates: list[tuple[str, str, int, int]] = []
    interface: str | None = None
    depth = 0
    seen: dict[str, int] = {}

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.split("//", maxsplit=1)[0]
        if interface is None:
            match = INTERFACE.match(line)
            if match is None:
                continue
            interface = match.group(1)
            seen = {}
            depth = line.count("{") - line.count("}")
            continue

        if depth == 1:
            match = TYPE_ITEM.match(line) or FUNCTION_ITEM.match(line)
            if match is not None:
                name = match.group(1)
                previous = seen.get(name)
                if previous is not None:
                    duplicates.append((interface, name, previous, line_number))
                else:
                    seen[name] = line_number

        depth += line.count("{") - line.count("}")
        if depth <= 0:
            interface = None
            seen = {}

    return duplicates


class WitContractTests(unittest.TestCase):
    def test_interface_item_names_are_unique(self) -> None:
        wit_files = sorted((ROOT / "wit").rglob("*.wit")) + sorted(
            (ROOT / "examples").rglob("*.wit")
        )
        self.assertGreater(len(wit_files), 0)
        failures: list[str] = []
        for path in wit_files:
            for interface, name, first_line, duplicate_line in duplicate_interface_items(
                path.read_text(encoding="utf-8")
            ):
                failures.append(
                    f"{path.relative_to(ROOT)}: interface {interface!r} defines {name!r} "
                    f"at both lines {first_line} and {duplicate_line}"
                )
        self.assertEqual(failures, [])

    def test_duplicate_detector_catches_type_function_collision(self) -> None:
        text = """
        interface context {
            record principal {
                subject: string,
            }
            principal: func() -> principal;
        }
        """
        self.assertEqual(
            duplicate_interface_items(text),
            [("context", "principal", 3, 6)],
        )

    def test_example_package_is_staged_with_platform_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "echo"
            source = ROOT / "examples" / "echo-contract" / "wit"
            stager.stage(destination, source)

            self.assertEqual(
                (destination / "echo.wit").read_text(encoding="utf-8"),
                (source / "echo.wit").read_text(encoding="utf-8"),
            )
            self.assertTrue((destination / "deps" / "context" / "package.wit").is_file())
            self.assertFalse((destination / "deps" / "runtime").exists())


if __name__ == "__main__":
    unittest.main()
