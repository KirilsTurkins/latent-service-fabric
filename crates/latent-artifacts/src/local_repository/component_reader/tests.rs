use std::cell::Cell;
use std::io::{self, Cursor};

use latent_core::PlatformErrorCode;

use super::*;
use crate::content_digest;

struct Fragmented<'a> {
    source: Cursor<&'a [u8]>,
    calls: usize,
}

impl Read for Fragmented<'_> {
    fn read(&mut self, output: &mut [u8]) -> io::Result<usize> {
        self.calls += 1;
        if self.calls == 1 || self.calls == 3 {
            return Err(io::ErrorKind::Interrupted.into());
        }
        let count = output.len().min(3);
        self.source.read(&mut output[..count])
    }
}

#[test]
fn short_reads_and_interruption_preserve_exact_digest_with_and_without_retention() {
    let payload = b"component read in short pieces";
    for retention in [Retention::Metadata, Retention::Component] {
        let mut reader = Fragmented {
            source: Cursor::new(payload.as_slice()),
            calls: 0,
        };
        let result =
            read_stream(&mut reader, payload.len() as u64, payload.len(), retention).unwrap();
        assert!(reader.calls > 3);
        assert_eq!(result.digest, content_digest(payload));
        assert_eq!(result.size, payload.len() as u64);
        match retention {
            Retention::Metadata => assert_eq!(result.bytes.capacity(), 0),
            Retention::Component => assert_eq!(result.bytes, payload),
        }
    }
}

struct Repeated<'a> {
    remaining: usize,
    largest_read: &'a Cell<usize>,
    consumed: &'a Cell<usize>,
}

impl Read for Repeated<'_> {
    fn read(&mut self, output: &mut [u8]) -> io::Result<usize> {
        self.largest_read
            .set(self.largest_read.get().max(output.len()));
        let count = output.len().min(self.remaining);
        output[..count].fill(b'a');
        self.remaining -= count;
        self.consumed.set(self.consumed.get() + count);
        Ok(count)
    }
}

#[test]
fn metadata_verification_has_fixed_scratch_and_no_retained_component_allocation() {
    let maximum = Cell::new(0);
    let consumed = Cell::new(0);
    for length in [
        0,
        55,
        56,
        SCRATCH_BYTES - 1,
        SCRATCH_BYTES,
        SCRATCH_BYTES + 1,
        1024 * 1024,
    ] {
        maximum.set(0);
        consumed.set(0);
        let reader = Repeated {
            remaining: length,
            largest_read: &maximum,
            consumed: &consumed,
        };
        let result = read_stream(reader, length as u64, length, Retention::Metadata).unwrap();
        assert_eq!(result.size, length as u64);
        assert_eq!(consumed.get(), length);
        assert!(maximum.get() <= SCRATCH_BYTES);
        assert!(result.bytes.is_empty());
        assert_eq!(result.bytes.capacity(), 0);
        if length == 1024 * 1024 {
            assert_eq!(
                result.digest.0,
                "sha256:9bc1b2a288b26af7257a36277ae3816a7d4f16e89c1e7e77d0a5c48bad62b360"
            );
        }
    }
}

#[test]
fn growth_is_observed_and_limit_plus_one_is_read_without_retention() {
    let maximum = Cell::new(0);
    let consumed = Cell::new(0);
    let reader = Repeated {
        remaining: 100,
        largest_read: &maximum,
        consumed: &consumed,
    };
    let error = read_stream(reader, 0, 7, Retention::Metadata)
        .err()
        .unwrap();
    assert_eq!(error.code, PlatformErrorCode::ResourceExhausted);
    assert_eq!(consumed.get(), 8);
    assert!(maximum.get() <= 8);
    for retention in [Retention::Metadata, Retention::Component] {
        let result = read_stream(Cursor::new(b"abc"), 0, 3, retention).unwrap();
        assert_eq!(result.size, 3);
        assert_eq!(result.digest, content_digest(b"abc"));
    }
}

#[test]
fn oversized_initial_length_is_rejected_before_any_read() {
    let maximum = Cell::new(0);
    let consumed = Cell::new(0);
    let reader = Repeated {
        remaining: 9,
        largest_read: &maximum,
        consumed: &consumed,
    };
    let error = read_stream(reader, 9, 8, Retention::Metadata)
        .err()
        .unwrap();
    assert_eq!(error.code, PlatformErrorCode::ResourceExhausted);
    assert_eq!(maximum.get(), 0);
    assert_eq!(consumed.get(), 0);
}

struct FailsAfterPrefix(bool);

impl Read for FailsAfterPrefix {
    fn read(&mut self, output: &mut [u8]) -> io::Result<usize> {
        if std::mem::replace(&mut self.0, true) {
            Err(io::ErrorKind::Other.into())
        } else {
            output[0] = b'a';
            Ok(1)
        }
    }
}

#[test]
fn partial_io_failure_never_returns_verified_metadata_or_partial_bytes() {
    for retention in [Retention::Metadata, Retention::Component] {
        let failure = read_stream(FailsAfterPrefix(false), 3, 3, retention)
            .err()
            .unwrap();
        assert_eq!(failure.code, PlatformErrorCode::CorruptArtifact);
        assert_eq!(failure.message, "completed release data cannot be read");
    }
}
