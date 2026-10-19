// Host reference of the actual PAL files with a synthetic typed-log bridge.
// This is not a rebuilt std, generated-binding, component or host qualification.
pub use std::{io, str};

#[path = "stdio_closed.rs"]
mod closed;
#[path = "stdio_logging.rs"]
mod logging;

use std::cell::{Cell, RefCell};
use std::io::{ErrorKind, IoSlice, Read, Write};

thread_local! {
    static STATUS: Cell<u8> = const { Cell::new(0) };
    static CALLS: RefCell<Vec<(u8, String)>> = const { RefCell::new(Vec::new()) };
}

#[unsafe(no_mangle)]
pub extern "Rust" fn __lsf_std_log_write_v1(level: u8, message: &str) -> u8 {
    CALLS.with(|calls| calls.borrow_mut().push((level, message.into())));
    STATUS.with(Cell::get)
}

fn reset(status: u8) {
    STATUS.with(|selected| selected.set(status));
    CALLS.with(|calls| calls.borrow_mut().clear());
}

#[test]
fn default_nonempty_output_write_all_and_flush_are_concrete_unsupported() {
    for output in [&mut closed::Stdout::new() as &mut dyn Write,
                       &mut closed::Stderr::new() as &mut dyn Write] {
        assert_eq!(output.write(b"outside").unwrap_err().kind(), ErrorKind::Unsupported);
        assert_eq!(output.write_all(b"outside").unwrap_err().kind(), ErrorKind::Unsupported);
        assert_eq!(output.flush().unwrap_err().kind(), ErrorKind::Unsupported);
        assert_eq!(output.write(&[]).unwrap(), 0);
        assert!(output.write_all(&[]).is_ok());
    }
    assert!(!closed::is_ebadf(&io::Error::from(ErrorKind::Unsupported)));
    assert!(closed::panic_output().is_none());
}

#[test]
fn default_nonempty_input_is_unsupported_rather_than_invented_eof() {
    assert_eq!(closed::Stdin::new().read(&mut [0]).unwrap_err().kind(), ErrorKind::Unsupported);
    assert_eq!(closed::Stdin::new().read(&mut []).unwrap(), 0);
    assert_eq!(logging::Stdin::new().read(&mut [0]).unwrap_err().kind(), ErrorKind::Unsupported);
}

#[test]
fn ordinary_write_fmt_and_write_all_use_exact_text_and_levels() {
    reset(0);
    write!(logging::Stdout::new(), "outside:{}", 17).unwrap();
    logging::Stderr::new().write_all("Gr\u{fc}\u{df}e".as_bytes()).unwrap();
    CALLS.with(|calls| {
        let calls = calls.borrow();
        let stdout: String = calls.iter().filter(|(level, _)| *level == 2).map(|(_, text)| text.as_str()).collect();
        assert_eq!(stdout, "outside:17");
        assert_eq!(calls.last().unwrap(), &(4, "Gr\u{fc}\u{df}e".into()));
        assert!(calls.iter().all(|(level, _)| [2, 4].contains(level)));
    });
    logging::Stdout::new().flush().unwrap();
}

#[test]
fn vectors_are_joined_before_utf8_validation_without_heap_or_partial_dispatch() {
    reset(0);
    let text = [IoSlice::new(b"Gr\xc3"), IoSlice::new(b"\xbc\xc3\x9fe")];
    assert_eq!(logging::Stdout::new().write_vectored(&text).unwrap(), 7);
    CALLS.with(|calls| assert_eq!(*calls.borrow(), vec![(2, "Gr\u{fc}\u{df}e".into())]));
    assert_eq!(logging::Stdout::new().write(b"\xc3").unwrap_err().kind(), ErrorKind::InvalidData);
    assert_eq!(logging::Stdout::new().write(b"\xff").unwrap_err().kind(), ErrorKind::InvalidData);
    CALLS.with(|calls| assert_eq!(calls.borrow().len(), 1));
}

#[test]
fn per_call_bytes_vectors_and_empty_inputs_do_not_dispatch_outside_bounds() {
    reset(0);
    assert_eq!(logging::Stdout::new().write(&[b'x'; 256]).unwrap(), 256);
    assert_eq!(logging::Stdout::new().write(&[b'x'; 257]).unwrap_err().kind(), ErrorKind::InvalidInput);
    let vectors = [IoSlice::new(b"x"); 17];
    assert_eq!(logging::Stderr::new().write_vectored(&vectors).unwrap_err().kind(), ErrorKind::InvalidInput);
    let empty_vectors = [IoSlice::new(b""); 17];
    assert_eq!(logging::Stderr::new().write_vectored(&empty_vectors).unwrap_err().kind(), ErrorKind::InvalidInput);
    assert_eq!(logging::Stdout::new().write(&[]).unwrap(), 0);
    assert_eq!(logging::Stderr::new().write_vectored(&[]).unwrap(), 0);
    CALLS.with(|calls| assert_eq!(calls.borrow().len(), 1));
}

#[test]
fn every_declared_provider_failure_and_reentrancy_remain_errors_without_retry() {
    for (status, expected) in [(1, ErrorKind::InvalidData), (2, ErrorKind::QuotaExceeded),
                              (3, ErrorKind::NotConnected), (4, ErrorKind::WouldBlock),
                              (5, ErrorKind::Other)] {
        reset(status);
        assert_eq!(logging::Stdout::new().write_all(b"outside").unwrap_err().kind(), expected);
        CALLS.with(|calls| assert_eq!(calls.borrow().len(), 1));
    }
}

#[test]
fn output_drop_has_no_hidden_host_write_or_panic_logger() {
    reset(0);
    { let _output = logging::Stdout::new(); let _error = logging::Stderr::new(); }
    CALLS.with(|calls| assert!(calls.borrow().is_empty()));
    assert!(logging::panic_output().is_none());
    assert!(!logging::is_ebadf(&io::Error::from(ErrorKind::Unsupported)));
    assert_eq!(closed::STDIN_BUF_SIZE, 0);
    assert_eq!(logging::STDIN_BUF_SIZE, 0);
}
