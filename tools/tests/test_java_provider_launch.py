"""Keep the Java 25 provider process profile explicit and narrowly scoped."""
from pathlib import Path
import re
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]
FLAGS = ("--sun-misc-unsafe-memory-access=allow", "--enable-native-access=ALL-UNNAMED")


class JavaProviderLaunchTests(unittest.TestCase):
    def test_only_java_participant_has_the_compatibility_flags(self):
        script = (ROOT / "tools/run_sdk_provider_matrix.sh").read_text()
        assignments = dict(re.findall(r"^\s*(rust|typescript|go|c|java|dotnet)\) (participant=.*?) ;;$", script, re.MULTILINE))
        self.assertEqual(set(assignments), {"rust", "typescript", "go", "c", "java", "dotnet"})
        for language, command in assignments.items():
            for flag in FLAGS:
                self.assertEqual(flag in command, language == "java")
        self.assertNotIn("JAVA_TOOL_OPTIONS", script)
        self.assertNotIn("JDK_JAVA_OPTIONS", script)
        self.assertNotIn("2>/dev/null", script)

    @unittest.skipUnless(shutil.which("bash"), "shell argument test requires bash")
    def test_flags_precede_jar_and_paths_remain_single_arguments(self):
        script = (ROOT / "tools/run_sdk_provider_matrix.sh").read_text()
        assignment = re.search(r"^\s*java\) (participant=.*?) ;;$", script, re.MULTILINE).group(1)
        # Shadow only the lookup, never execute a JVM or download a toolchain.
        shell = 'command() { printf "%s\\n" "/selected JDK/bin/java"; }; ROOT="/source with spaces"; '
        shell += assignment + '; printf "%s\\0" "${participant[@]}"'
        result = subprocess.run([shutil.which("bash"), "-eu", "-c", shell], capture_output=True, check=True, timeout=5)
        self.assertEqual(result.stderr, b"")
        self.assertEqual(result.stdout.decode().split("\0")[:-1], [
            "/selected JDK/bin/java", *FLAGS, "-jar",
            "/source with spaces/sdk/java-client/build/latent-java-client.jar",
        ])

    def test_default_sdk_tests_keep_jvm_warnings_visible(self):
        for relative in ("sdk/java-client/tools/build.py", "sdk/java-client/build.gradle.kts"):
            text = (ROOT / relative).read_text()
            for flag in FLAGS:
                self.assertNotIn(flag, text)
        runner = (ROOT / "tools/sdk_provider_scenario.py").read_text()
        self.assertIn("result.returncode == 0 and not result.stderr", runner)


if __name__ == "__main__":
    unittest.main()
