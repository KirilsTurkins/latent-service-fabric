"""State page ownership using the real Java wrapper and stubbed host bindings."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

SDK = Path(__file__).resolve().parents[1]


class StatePageOwnership(unittest.TestCase):
    @unittest.skipUnless(shutil.which("javac") and shutil.which("java"), "native JDK controls")
    def test_page_close_retains_parent_on_borrow_and_uncertain_destructor(self):
        runtime = SDK / "runtime/dev/latent/guest"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = root / "State.java"
            shutil.copyfile(runtime / "State.java.in", state)
            sources = [runtime / name for name in ("Resource.java", "Result.java", "Option.java", "Unit.java")]
            sources.extend((SDK / "tests/state-page").rglob("*.java"))
            subprocess.run(["javac", "-proc:none", "-encoding", "UTF-8", "-d", str(root),
                            *map(str, sources), str(state)], check=True)
            subprocess.run(["java", "-cp", str(root), "dev.latent.guest.PageCheck"], check=True)


if __name__ == "__main__":
    unittest.main()
