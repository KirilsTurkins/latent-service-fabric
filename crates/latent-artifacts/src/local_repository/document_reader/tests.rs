use std::cell::Cell;
use std::io::{self, Cursor};

use latent_core::PlatformErrorCode;

use super::*;

struct Observed<'a> {
    source: Cursor<&'a [u8]>,
    consumed: &'a Cell<usize>,
    interrupt: bool,
}

impl Read for Observed<'_> {
    fn read(&mut self, output: &mut [u8]) -> io::Result<usize> {
        if std::mem::take(&mut self.interrupt) {
            return Err(ErrorKind::Interrupted.into());
        }
        let available = output.len().min(2);
        let count = self.source.read(&mut output[..available])?;
        self.consumed.set(self.consumed.get() + count);
        Ok(count)
    }
}

#[test]
fn exact_limit_short_reads_and_interruption_preserve_documents() {
    let consumed = Cell::new(0);
    let input = b"bounded metadata";
    let reader = Observed {
        source: Cursor::new(input),
        consumed: &consumed,
        interrupt: true,
    };
    assert_eq!(read_stream(reader, 0, input.len(), "test").unwrap(), input);
    assert_eq!(consumed.get(), input.len());
    assert!(read_stream(Cursor::new([]), 0, 0, "empty")
        .unwrap()
        .is_empty());
}

#[test]
fn growth_reads_only_the_sentinel_and_never_returns_partial_documents() {
    let consumed = Cell::new(0);
    let reader = Observed {
        source: Cursor::new(b"abcdefgh"),
        consumed: &consumed,
        interrupt: false,
    };
    assert_eq!(
        read_stream(reader, 0, 3, "test").unwrap_err().code,
        PlatformErrorCode::ResourceExhausted
    );
    assert_eq!(consumed.get(), 4);
}

#[test]
fn excessive_initial_length_is_rejected_without_reading() {
    let consumed = Cell::new(0);
    let reader = Observed {
        source: Cursor::new(b"abc"),
        consumed: &consumed,
        interrupt: false,
    };
    assert_eq!(
        read_stream(reader, 4, 3, "test").unwrap_err().code,
        PlatformErrorCode::ResourceExhausted
    );
    assert_eq!(consumed.get(), 0);
}

struct FailsAfterPrefix(bool);

impl Read for FailsAfterPrefix {
    fn read(&mut self, output: &mut [u8]) -> io::Result<usize> {
        if std::mem::replace(&mut self.0, true) {
            Err(ErrorKind::Other.into())
        } else {
            output[0] = b'a';
            Ok(1)
        }
    }
}

#[test]
fn read_error_discards_partial_document() {
    let failure = read_stream(FailsAfterPrefix(false), 3, 3, "test").unwrap_err();
    assert_eq!(failure.code, PlatformErrorCode::CorruptArtifact);
    assert_eq!(failure.message, "completed release data cannot be read");
}
