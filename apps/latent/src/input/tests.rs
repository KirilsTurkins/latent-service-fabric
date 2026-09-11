use std::fs;
use std::io::Cursor;
use std::path::Path;

use super::{read, read_bounded, single_stdin};

#[test]
fn reader_checks_actual_bytes_and_stops_after_one_sentinel_byte() {
    let mut reader = Cursor::new(b"abcdef");
    assert!(read_bounded(&mut reader, 3, "payload").is_err());
    assert_eq!(reader.position(), 4);
    let exact =
        read_bounded(Cursor::new(b"abc"), 3, "payload").unwrap_or_else(|_| panic!("exact limit"));
    assert_eq!(exact, b"abc");
    assert!(read_bounded(Cursor::new(b""), 0, "payload").is_ok());
    assert!(read_bounded(Cursor::new(b"a"), 0, "payload").is_err());
    assert!(read_bounded(Cursor::new(b"a"), usize::MAX, "payload").is_err());
}

#[test]
fn file_reads_and_stdin_ownership_are_explicit() {
    let directory = tempfile::tempdir().expect("temporary directory");
    let path = directory.path().join("payload.bin");
    fs::write(&path, [0, 255, 10]).expect("binary input");
    let bytes = read(&path, 3, "payload").unwrap_or_else(|_| panic!("bounded input"));
    assert_eq!(bytes, [0, 255, 10]);
    assert!(read(&path, 2, "payload").is_err());
    assert!(read(directory.path(), 16, "payload").is_err());
    assert!(single_stdin(&[Path::new("-"), &path]).is_ok());
    assert!(single_stdin(&[Path::new("-"), &path, Path::new("-")]).is_err());
}
