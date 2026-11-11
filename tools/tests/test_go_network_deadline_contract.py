"""Mutations of the source guard; these are not physical deadline evidence."""
from pathlib import Path
import unittest

from tools.go_network_deadline_reference import pending_deadline_contract

ROOT = Path(__file__).resolve().parents[2]

# Small source-shape double. The repository-source case below checks the actual
# provider separately; no fake Rust text is supplied to a runtime qualification.
PENDING = b'''    fn pending(
        self: &Arc<Self>, direction: usize, timeout: Option<u32>,
    ) -> Result<Pending, StreamError> {
        if timeout.is_some_and(|value| value > 10_000 || (value == 0 && direction != 2)) {
            return Err(error(StreamErrorCode::InvalidInput));
        }
        let mut deadline = self.deadline.min(state.last_progress + self.idle);
        let observation = direction == 2 && !socket.host_tls() && !socket.protected_owner();
        let requested = timeout.map(|value| now + Duration::from_millis(u64::from(value)));
        if !observation {
            if let Some(requested) = requested {
                deadline = deadline.min(requested);
            }
        }
        if now >= deadline {
            return Err(error(StreamErrorCode::Timeout).uncertain(state.attempted_write));
        }
        Ok(Pending {
            deadline,
            observation_deadline: if observation { requested } else { None },
            observation_immediate: observation && timeout == Some(0),
        })
    }
'''


def callers(read=0, write=1, ready=2):
    return b''.join(
        f'''    fn {operation}(
        &self, timeout: Option<u32>,
    ) {{
        let pending = self.connection.pending({direction}, timeout)?;
    }}
'''.encode()
        for operation, direction in (('read', read), ('write_from', write), ('ready', ready))
    )


class PendingDeadlineGuardTests(unittest.TestCase):
    def assert_refused(self, source):
        with self.assertRaisesRegex(ValueError, 'go-network-deadline-pending-'):
            pending_deadline_contract(source)

    def test_selected_readiness_split_is_accepted(self):
        pending_deadline_contract(PENDING + callers())

    def test_whitespace_in_the_selected_method_is_not_a_fingerprint(self):
        source = PENDING.replace(b'        let ', b'\n        let ')
        source = source.replace(b'if !observation {', b'if !observation {\n')
        pending_deadline_contract(source + callers())

    def test_timeout_limits_and_original_lifetime_cannot_be_widened(self):
        mutations = (
            (b'value > 10_000', b'value > 20_000'),
            (b'direction != 2', b'direction != 0'),
            (b'self.deadline.min(state.last_progress + self.idle)', b'self.deadline'),
            (b'deadline.min(requested)', b'requested'),
            (b'if !observation {', b'if observation {'),
            (b'if now >= deadline {', b'if now > deadline {'),
        )
        for old, new in mutations:
            with self.subTest(marker=old):
                self.assertEqual(PENDING.count(old), 1)
                self.assert_refused(PENDING.replace(old, new) + callers())

    def test_observation_exception_remains_plain_tcp_readiness_only(self):
        for old in (b'direction == 2 && ', b'!socket.host_tls() && ',
                    b' && !socket.protected_owner()'):
            with self.subTest(marker=old):
                self.assertEqual(PENDING.count(old), 1)
                self.assert_refused(PENDING.replace(old, b'') + callers())
        self.assert_refused(PENDING.replace(b'if observation { requested } else { None }',
                                            b'requested') + callers())
        self.assert_refused(PENDING.replace(b'observation && timeout == Some(0)',
                                            b'timeout == Some(0)') + callers())

    def test_duplicate_missing_or_out_of_scope_methods_are_refused(self):
        self.assert_refused(callers())
        self.assert_refused(PENDING + PENDING + callers())
        self.assert_refused(PENDING.replace(b'fn pending(', b'fn elsewhere(') + callers())
        # A matching guard elsewhere cannot compensate for a changed real guard.
        changed = PENDING.replace(b'deadline.min(requested)', b'requested')
        self.assert_refused(changed + PENDING.replace(b'fn pending(', b'fn elsewhere(') + callers())

    def test_callers_cannot_swap_read_write_or_readiness_directions(self):
        for directions in ((2, 1, 0), (0, 2, 1), (1, 0, 2), (0, 1, 3)):
            with self.subTest(directions=directions):
                self.assert_refused(PENDING + callers(*directions))
        self.assert_refused(PENDING + callers() + callers())


class RepositoryPendingDeadlineTests(unittest.TestCase):
    def test_current_provider_keeps_the_selected_deadline_contract(self):
        pending_deadline_contract((ROOT / 'crates/latent-streams/src/connection.rs').read_bytes())


if __name__ == '__main__':
    unittest.main()
