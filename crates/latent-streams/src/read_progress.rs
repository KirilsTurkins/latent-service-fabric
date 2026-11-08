//! Development-only observations of the original pending read guards.
//!
//! These counters are not another resource ledger. Releasing a read guard does
//! not retire its result chunk, connection, IoCall, kernel tail or activation.
use crate::{error, StreamError, StreamErrorCode};

/// Read-guard progress for the live owners included in a usage snapshot.
///
/// A single connection admits at most one read guard at a time. The next read
/// cannot be admitted until the previous guard releases its copied transport.
/// Counters include unpolled reads and reads whose later buffer admission fails;
/// neither admission nor release implies successful dispatch or delivery.
///
/// Provider/lifecycle snapshots sum live owners, not an activation's history.
/// Qualification must isolate the intended owner before interpreting a sequence.
/// This observation is deliberately absent from serialized operator status.
#[derive(Debug, Default, Clone, Copy, PartialEq, Eq)]
pub struct StreamReadProgress {
    admitted: u64,
    released: u64,
    released_bytes: u64,
}

impl StreamReadProgress {
    #[must_use]
    pub fn admitted(self) -> u64 {
        self.admitted
    }

    #[must_use]
    pub fn released(self) -> u64 {
        self.released
    }

    #[must_use]
    pub fn pending(self) -> u64 {
        self.admitted - self.released
    }

    /// Transport bytes observed before those guards released, not proof that
    /// the guest consumed a result or that a remote mutation rolled back.
    #[must_use]
    pub fn released_bytes(self) -> u64 {
        self.released_bytes
    }

    pub(crate) fn admit(&mut self) -> Result<(), StreamError> {
        if self.pending() != 0 {
            return Err(error(StreamErrorCode::InvalidState));
        }
        self.admitted = self
            .admitted
            .checked_add(1)
            .ok_or_else(|| error(StreamErrorCode::Exhausted))?;
        Ok(())
    }

    pub(crate) fn release(&mut self, delivered_bytes: u64) {
        debug_assert_eq!(self.pending(), 1, "one original read guard releases once");
        debug_assert!(delivered_bytes >= self.released_bytes);
        self.released = self.admitted;
        self.released_bytes = delivered_bytes;
    }

    pub(crate) fn merge(&mut self, next: Self) -> Result<(), StreamError> {
        let admitted = self
            .admitted
            .checked_add(next.admitted)
            .ok_or_else(|| error(StreamErrorCode::Exhausted))?;
        let released = self
            .released
            .checked_add(next.released)
            .ok_or_else(|| error(StreamErrorCode::Exhausted))?;
        let released_bytes = self
            .released_bytes
            .checked_add(next.released_bytes)
            .ok_or_else(|| error(StreamErrorCode::Exhausted))?;
        // Publish the whole observation together; overflow leaves the old value.
        *self = Self {
            admitted,
            released,
            released_bytes,
        };
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_second_read_requires_release_of_the_first_guard() {
        let mut progress = StreamReadProgress::default();
        progress.admit().unwrap();
        assert_eq!(progress.admitted(), 1);
        assert_eq!(progress.released(), 0);
        assert_eq!(progress.pending(), 1);
        assert_eq!(progress.released_bytes(), 0);
        let first = progress;
        assert_eq!(
            progress.admit().unwrap_err().code,
            StreamErrorCode::InvalidState
        );
        assert_eq!(progress, first);
        progress.release(1);
        progress.admit().unwrap();
        assert_eq!(progress.admitted(), 2);
        assert_eq!(progress.released(), 1);
        assert_eq!(progress.pending(), 1);
        assert_eq!(progress.released_bytes(), 1);
        progress.release(1);
        assert_eq!(progress.admitted(), 2);
        assert_eq!(progress.released(), 2);
        assert_eq!(progress.pending(), 0);
    }

    #[test]
    fn read_sequence_exhaustion_never_wraps_or_reuses_an_identity() {
        let mut progress = StreamReadProgress {
            admitted: u64::MAX,
            released: u64::MAX,
            released_bytes: 0,
        };
        let original = progress;
        assert_eq!(
            progress.admit().unwrap_err().code,
            StreamErrorCode::Exhausted
        );
        assert_eq!(progress, original);
        assert_eq!(progress.pending(), 0);
    }

    #[test]
    fn live_owner_aggregation_is_checked_and_does_not_partially_publish() {
        let mut progress = StreamReadProgress {
            admitted: 2,
            released: 1,
            released_bytes: 1,
        };
        progress
            .merge(StreamReadProgress {
                admitted: 3,
                released: 3,
                released_bytes: 2,
            })
            .unwrap();
        assert_eq!(progress.admitted(), 5);
        assert_eq!(progress.released(), 4);
        assert_eq!(progress.pending(), 1);
        assert_eq!(progress.released_bytes(), 3);
        let original = progress;
        for overflow in [
            StreamReadProgress {
                admitted: u64::MAX,
                released: u64::MAX,
                released_bytes: 0,
            },
            StreamReadProgress {
                admitted: 1,
                released: 1,
                released_bytes: u64::MAX,
            },
        ] {
            assert_eq!(
                progress.merge(overflow).unwrap_err().code,
                StreamErrorCode::Exhausted
            );
            assert_eq!(progress, original);
        }
    }
}
