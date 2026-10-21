//! Exact diagnostic stream with explicit LOG/error/quota test ports only.
use std::cell::{Cell, RefCell};
pub mod quota { pub struct Slot; impl Slot { pub fn new()->Self { Self } } }
pub struct ClosedError { _slot: quota::Slot }
pub mod exports { pub mod wasi { pub mod io {
    pub mod error { pub struct Error; impl Error { pub fn new(_:crate::ClosedError)->Self {Self} } }
    pub mod streams { pub enum StreamError { LastOperationFailed(super::error::Error) } }
} } }
pub mod latent { pub mod log { pub mod log {
    use crate::*;
    pub enum Level { Error }
    thread_local! {
        pub static VALUES:RefCell<Vec<String>>=RefCell::new(Vec::new());
        pub static ACCEPT:Cell<bool>=const{Cell::new(true)};
    }
    pub fn write(_:Level,text:&str,fields:&[()])->Result<bool,()> {
        assert!(fields.is_empty()); VALUES.with(|v|v.borrow_mut().push(text.into()));
        Ok(ACCEPT.get())
    }
} } }
#[path="dotnet-periodic-console.rs"] mod console;
use latent::log::log::{ACCEPT,VALUES};
fn reset() { VALUES.with(|v|v.borrow_mut().clear());ACCEPT.set(true); }
fn write(stream:&console::Stream,bytes:&[u8]) {
    assert_eq!(stream.check_write().ok(),Some(256));assert!(stream.write(bytes.to_vec()).is_ok());
}
fn captured()->Vec<String> { VALUES.with(|v|v.borrow().clone()) }
#[test]
fn every_closed_code_is_chunk_safe_and_emits_one_length_only() {
    for code in 0..=console::CODES.len() {
        for chunk in 1..=256 {
            reset();let stream=console::stderr().unwrap();
            let text=format!("LSF-PERIODIC-CODE:{code:04}\nProcess terminated. TimerQueue.TimerHandler failed\nprivate/path\n");
            for bytes in text.as_bytes().chunks(chunk) { write(&stream,bytes); }
            assert!(stream.flush().is_ok());assert_eq!(captured(),vec!["p".repeat(code+1)]);
        }
    }
}
#[test]
fn unknown_text_and_lookalike_markers_never_classify() {
    for text in [b"TimerQueue.TimerHandler failed\nmanaged-work-parent-retired\n".as_slice(),
        b"prefix LSF-PERIODIC-CODE:0001\n",b"LSF-PERIODIC-CODE:9999\n",
        b"LSF-PERIODIC-CODE:001\n",b"LSF-PERIODIC-CODE:0001-private\n"] {
        reset();let stream=console::stderr().unwrap();for bytes in text.chunks(7) {write(&stream,bytes);}
        assert!(captured().is_empty());
    }
    reset();let stream=console::stderr().unwrap();
    let mut prefix=vec![b'x';128];prefix.extend_from_slice(b"LSF-PERIODIC-CODE:0001\n");prefix.resize(256,b'x');
    write(&stream,&prefix);write(&stream,b"x");
    assert!(captured().is_empty());
    assert!(console::stdout().is_none());
}
#[test]
fn original_failfast_text_is_discarded_and_only_one_code_is_emitted() {
    reset();let stream=console::stderr().unwrap();
    write(&stream,b"private arbitrary exception\nLSF-PERIODIC-CODE:0002\n");
    write(&stream,b"LSF-PERIODIC-CODE:0003\nSystem.Exception: private\n");
    assert_eq!(captured(),vec!["ppp"]);
    reset();let stream=console::stderr().unwrap();
    write(&stream,b"LSF-PERIODIC-CODE:0037\nLSF-PERIODIC-CODE:0001\n");
    assert_eq!(captured(),vec!["p".repeat(38)]);
}
#[test]
fn original_input_and_per_write_bounds_fail_closed_without_raw_output() {
    reset();let stream=console::stderr().unwrap();
    for _ in 0..32 {write(&stream,&[b'x';256]);}
    assert!(stream.check_write().is_ok());assert!(stream.write(vec![b'x']).is_err());
    assert!(stream.flush().is_err());assert!(captured().is_empty());
    reset();let stream=console::stderr().unwrap();assert!(stream.check_write().is_ok());
    assert!(stream.write(vec![b'x';257]).is_err());assert!(captured().is_empty());
}
#[test]
fn rejected_log_is_not_retried_or_accepted_as_a_diagnostic() {
    reset();ACCEPT.set(false);let stream=console::stderr().unwrap();
    assert!(stream.check_write().is_ok());
    assert!(stream.write(b"LSF-PERIODIC-CODE:0001\n".to_vec()).is_err());
    assert_eq!(captured().len(),1);assert!(stream.check_write().is_err());
    assert!(stream.flush().is_err());assert_eq!(captured().len(),1);
}
