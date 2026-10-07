"""Native UTF-8 reference equivalence; this does not qualify a compiled component."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from tools.java_capsule_project import ROOT


class WireUtf8(unittest.TestCase):
    @unittest.skipUnless(shutil.which("javac") and shutil.which("java"), "native JDK controls")
    def test_original_utf8_rejections_bounds_and_strings_match_native_references(self):
        sdk = ROOT / "sdk/java-guest"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            interop = root / "org/teavm/interop"
            interop.mkdir(parents=True)
            # Declarations only: none of the bridge imports is invoked by this
            # Reader/string control. An accidental native call fails linkage.
            (interop / "Address.java").write_text(
                "package org.teavm.interop; public final class Address {"
                "public native Address add(int offset); public native byte getByte();"
                "public native int getInt(); public native void putByte(byte value);"
                "public static native Address ofData(byte[] value); }\n", encoding="utf-8")
            (interop / "Import.java").write_text(
                "package org.teavm.interop; public @interface Import { String name(); }\n", encoding="utf-8")
            sources = [sdk / "runtime/dev/latent/guest/Wire.java",
                       sdk / "runtime/dev/latent/guest/Resource.java",
                       sdk / "tests/wire/WireUtf8Control.java",
                       interop / "Address.java", interop / "Import.java"]
            subprocess.run(["javac", "-proc:none", "-encoding", "UTF-8", "-d", str(root), *map(str, sources)],
                           check=True, capture_output=True, timeout=30)
            result = subprocess.run(["java", "-Xmx256m", "-cp", str(root), "dev.latent.guest.WireUtf8Control"],
                                    check=True, capture_output=True, text=True, timeout=15)
            self.assertIn("WIRE_UTF8_SOURCE_CONTROL PASS cases=9466;", result.stdout)
            self.assertIn("large-ascii;original-bounds;writer-surrogates;COMPONENT_QUALIFICATION=pending", result.stdout)
            print(result.stdout.rstrip())


if __name__ == "__main__":
    unittest.main()
