"""Run only the existing lost-ACK broker case for a diagnostic branch."""
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "tools"))
from tools import run_nats_deferred_tests as owner

original = owner.test_command

def selected(manifest, suite):
    command = original(manifest, suite)
    if command.count("real_deferred_") != 1:
        raise RuntimeError("unexpected original test selector")
    command[command.index("real_deferred_")] = (
        "real_deferred_lost_acknowledgement_retries_exact_id_once_with_one_broker_message")
    return command

owner.test_command = selected
raise SystemExit(owner.main())
