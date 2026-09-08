use std::io::Read;
use std::sync::{Arc, Mutex};
use std::thread::{self, JoinHandle};

const MAXIMUM_OUTPUT_BYTES: usize = 64 * 1024;

#[derive(Default)]
struct State {
    bytes: Vec<u8>,
    failed: bool,
}

#[derive(Clone, Default)]
pub(super) struct Capture(Arc<Mutex<State>>);

impl Capture {
    pub(super) fn read(&self, mut reader: impl Read + Send + 'static) -> JoinHandle<()> {
        let capture = self.clone();
        thread::spawn(move || {
            let mut buffer = [0_u8; 1024];
            loop {
                let count = match reader.read(&mut buffer) {
                    Ok(0) => break,
                    Ok(count) => count,
                    Err(_) => {
                        capture.0.lock().unwrap().failed = true;
                        break;
                    }
                };
                let mut state = capture.0.lock().unwrap();
                if count > MAXIMUM_OUTPUT_BYTES.saturating_sub(state.bytes.len()) {
                    state.failed = true;
                    break;
                }
                state.bytes.extend_from_slice(&buffer[..count]);
            }
        })
    }

    pub(super) fn check(&self) {
        assert!(
            !self.0.lock().unwrap().failed,
            "child output was invalid or exceeded 64KiB"
        );
    }

    pub(super) fn bytes(&self) -> Vec<u8> {
        self.0.lock().unwrap().bytes.clone()
    }
}
