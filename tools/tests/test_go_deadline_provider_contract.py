"""Negative controls for the source-bound Go deadline reference, not live I/O."""
from pathlib import Path
import unittest

from tools import go_network_deadline_reference as deadline

ROOT = Path(__file__).resolve().parents[2]


class GoDeadlineProviderContractTests(unittest.TestCase):
    def test_current_provider_preserves_the_io_deadline_contract(self):
        template = (ROOT / 'sdk/go-guest/runtime/net_stream.go.in').read_bytes()
        materials = {path: (ROOT / path).read_bytes() for path in deadline.MATERIALS}
        deadline.contract(template, materials)

    def test_readiness_exception_cannot_relax_io_deadlines(self):
        template = (ROOT / 'sdk/go-guest/runtime/net_stream.go.in').read_bytes()
        materials = {path: (ROOT / path).read_bytes() for path in deadline.MATERIALS}
        connection = 'crates/latent-streams/src/connection.rs'
        mutations = (
            (b'value > 10_000 || (value == 0 && direction != 2)',
             b'value > 20_000 || (value == 0 && direction != 2)'),
            (b'value > 10_000 || (value == 0 && direction != 2)',
             b'value > 10_000'),
            (b'let observation = direction == 2 && !socket.host_tls() && !socket.protected_owner();',
             b'let observation = true;'),
            (b'let mut deadline = self.deadline.min(state.last_progress + self.idle);',
             b'let mut deadline = self.deadline;'),
            (b'let requested = timeout.map(|value| now + Duration::from_millis(u64::from(value)));',
             b'let requested = timeout.map(|value| now + Duration::from_secs(u64::from(value)));'),
            (b'if !observation {\n            if let Some(requested) = requested {\n                deadline = deadline.min(requested);',
             b'if observation {\n            if let Some(requested) = requested {\n                deadline = deadline.min(requested);'),
            (b'deadline = deadline.min(requested);', b'deadline = requested;'),
        )
        deadline.contract(template, materials)
        for old, new in mutations:
            with self.subTest(marker=old):
                self.assertEqual(materials[connection].count(old), 1)
                changed = dict(materials)
                changed[connection] = materials[connection].replace(old, new, 1)
                with self.assertRaisesRegex(ValueError, 'go-network-deadline-provider-or-context-drift'):
                    deadline.contract(template, changed)


if __name__ == '__main__':
    unittest.main()
