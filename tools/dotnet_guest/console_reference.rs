//! Actual stdio port source against a bounded fake canonical log import.
//! This host reference does not qualify the WASI ABI, BCL or a signed component.
use std::sync::atomic::{AtomicUsize, Ordering};
static ACTIVE: AtomicUsize = AtomicUsize::new(0);
mod quota {
    pub struct Slot;
    impl Slot {
        pub fn new() -> Self {
            super::ACTIVE.fetch_add(1, super::Ordering::SeqCst);
            Self
        }
    }
    impl Drop for Slot {
        fn drop(&mut self) {
            super::ACTIVE.fetch_sub(1, super::Ordering::SeqCst);
        }
    }
}
struct ClosedError {
    _slot: quota::Slot,
}
mod exports {
    pub mod wasi {
        pub mod io {
            pub mod error {
                pub struct Error {
                    pub _inner: Box<crate::ClosedError>,
                }
                impl Error {
                    pub fn new(inner: crate::ClosedError) -> Self {
                        Self {
                            _inner: Box::new(inner),
                        }
                    }
                }
            }
            pub mod streams {
                pub enum StreamError {
                    Closed,
                    LastOperationFailed(super::error::Error),
                }
            }
        }
    }
}
mod latent {
    pub mod log {
        pub mod log {
            use std::{
                cell::{Cell, RefCell},
                rc::Rc,
            };
            #[derive(Clone, Copy, Debug, PartialEq, Eq)]
            pub enum Level {
                Info,
                Error,
            }
            pub struct Field;
            #[derive(Clone, Copy)]
            pub enum LogError {
                BudgetExhausted,
                InvalidField,
                Unavailable,
            }
            thread_local! {
                pub static MODE: Cell<u8> = const { Cell::new(0) };
                pub static CALLS: RefCell<Vec<(Level, String)>> = const { RefCell::new(Vec::new()) };
                pub static REENTER: RefCell<Option<Rc<crate::console::Stream>>> = const { RefCell::new(None) };
            }
            pub fn write(level: Level, text: &str, fields: &[Field]) -> Result<bool, LogError> {
                assert!(fields.is_empty()); // Guest text cannot supply correlation fields.
                assert!(text.len() <= 256);
                CALLS.with(|calls| calls.borrow_mut().push((level, text.to_owned())));
                let reenter = REENTER.with(|slot| slot.borrow_mut().take());
                if let Some(stream) = reenter {
                    assert!(stream.check_write().is_err());
                }
                match MODE.get() {
                    0 => Ok(true),
                    1 => Ok(false),
                    2 => Err(LogError::BudgetExhausted),
                    3 => Err(LogError::InvalidField),
                    _ => Err(LogError::Unavailable),
                }
            }
        }
    }
}
#[path = "../../sdk/dotnet-guest/runtime/console/closed.rs"]
mod closed;
#[path = "../../sdk/dotnet-guest/runtime/console/logging.rs"]
mod console;
use latent::log::log::{CALLS, Level, MODE, REENTER};
fn reset() {
    assert_eq!(ACTIVE.load(Ordering::SeqCst), 0);
    MODE.set(0);
    CALLS.with(|calls| calls.borrow_mut().clear());
    REENTER.with(|slot| slot.borrow_mut().take());
}
fn sent() -> Vec<(Level, String)> {
    CALLS.with(|calls| calls.borrow().clone())
}
fn accepted(stream: &console::Stream, bytes: &[u8]) {
    assert!(stream.check_write().is_ok());
    assert!(stream.write(bytes.to_vec()).is_ok());
}
fn failed(result: Result<(), exports::wasi::io::streams::StreamError>) {
    match result {
        Err(exports::wasi::io::streams::StreamError::LastOperationFailed(error)) => drop(error),
        _ => panic!("expected an actual stream failure"),
    }
    assert_eq!(ACTIVE.load(Ordering::SeqCst), 0);
}
#[test]
fn exact_text_and_levels_cannot_supply_guest_correlation_fields() {
    reset();
    let output = console::stdout().unwrap();
    let error = console::stderr().unwrap();
    accepted(&output, b"{\"tenant\":\"different\"}\n");
    accepted(&error, "Gr\u{fc}\u{df}e".as_bytes());
    assert!(output.flush().is_ok());
    assert!(error.flush().is_ok());
    assert_eq!(
        sent(),
        vec![
            (Level::Info, "{\"tenant\":\"different\"}\n".into()),
            (Level::Error, "Gr\u{fc}\u{df}e".into())
        ]
    );
}
#[test]
fn split_utf8_keeps_exact_bytes_with_at_most_three_pending_bytes() {
    reset();
    let output = console::stdout().unwrap();
    accepted(&output, b"Gr\xc3");
    assert_eq!(output.check_write().ok(), Some(255));
    accepted(&output, b"\xbc\xc3\x9f");
    accepted(&output, b"e");
    accepted(&output, b"\xf0\x9f\x8c");
    assert_eq!(output.check_write().ok(), Some(253));
    accepted(&output, b"\x8d");
    assert!(output.flush().is_ok());
    assert_eq!(
        sent().into_iter().map(|(_, text)| text).collect::<String>(),
        "Gr\u{fc}\u{df}e\u{1f30d}"
    );
}
#[test]
fn malformed_or_unfinished_text_fails_strictly_before_invalid_host_dispatch() {
    reset();
    for bytes in [
        vec![255],
        vec![0xc0, 0x80],
        vec![0xed, 0xa0, 0x80],
        vec![0xf4, 0x90, 0x80, 0x80],
    ] {
        let output = console::stdout().unwrap();
        assert!(output.check_write().is_ok());
        failed(output.write(bytes));
        failed(output.flush());
        assert!(sent().is_empty());
    }
    let output = console::stdout().unwrap();
    accepted(&output, &[0xc3]);
    failed(output.flush());
    failed(output.write(Vec::new()));
    assert!(sent().is_empty());
}
#[test]
fn drops_budget_invalid_and_unavailable_never_become_delivery_or_retry() {
    reset();
    for mode in 1..=4 {
        MODE.set(mode);
        let output = console::stdout().unwrap();
        assert!(output.check_write().is_ok());
        let before = sent().len();
        failed(output.write(b"message".to_vec()));
        failed(output.flush());
        assert!(output.check_write().is_err());
        assert_eq!(sent().len(), before + 1);
    }
    assert_eq!(ACTIVE.load(Ordering::SeqCst), 0);
}
#[test]
fn original_stream_permit_and_message_byte_limits_apply_before_dispatch() {
    reset();
    let output = console::stdout().unwrap();
    failed(output.write(b"without check-write".to_vec()));
    assert!(sent().is_empty());
    let output = console::stdout().unwrap();
    assert!(output.write(Vec::new()).is_ok());
    assert!(output.flush().is_ok());
    assert!(sent().is_empty());
    assert_eq!(output.check_write().ok(), Some(256));
    assert!(output.write(vec![b'a'; 256]).is_ok());
    assert_eq!(sent().len(), 1);
    assert!(output.check_write().is_ok());
    failed(output.write(vec![b'a'; 257]));
    assert_eq!(sent().len(), 1);
}
#[test]
fn dropping_partial_text_adds_no_hidden_flush_or_worker() {
    reset();
    {
        let output = console::stdout().unwrap();
        accepted(&output, &[0xc3]);
    }
    assert!(sent().is_empty());
    assert_eq!(ACTIVE.load(Ordering::SeqCst), 0);
}
#[test]
fn overlapping_raw_handle_operation_cannot_falsely_acknowledge_outer_write() {
    reset();
    let output = std::rc::Rc::new(console::stdout().unwrap());
    REENTER.with(|slot| slot.replace(Some(output.clone())));
    assert!(output.check_write().is_ok());
    failed(output.write(b"attempt".to_vec()));
    assert_eq!(sent().len(), 1);
    failed(output.flush());
}
#[test]
fn default_closed_selection_stays_closed_and_has_no_log_effect() {
    reset();
    assert!(closed::stdout().is_none());
    assert!(closed::stderr().is_none());
    let stream = closed::Stream;
    assert!(stream.check_write().is_err());
    assert!(stream.write(Vec::new()).is_err());
    assert!(stream.flush().is_err());
    assert!(sent().is_empty());
}
