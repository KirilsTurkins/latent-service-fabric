// Closed standard streams; subscriptions report their actual closed state.
struct ClosedInput {
    _slot: quota::Slot,
}
struct ClosedOutput {
    console: Option<console::Stream>,
    _slot: quota::Slot,
}
struct ClosedError {
    _slot: quota::Slot,
}
impl ClosedInput {
    fn closed() -> Self {
        Self {
            _slot: quota::Slot::new(),
        }
    }
}
impl ClosedOutput {
    fn stdout() -> Self {
        Self {
            console: console::stdout(),
            _slot: quota::Slot::new(),
        }
    }
    fn stderr() -> Self {
        Self {
            console: console::stderr(),
            _slot: quota::Slot::new(),
        }
    }
}
impl exports::wasi::io::streams::GuestInputStream for ClosedInput {
    fn read(&self, len: u64) -> Result<Vec<u8>, exports::wasi::io::streams::StreamError> {
        if len == 0 {
            Ok(Vec::new())
        } else {
            Err(exports::wasi::io::streams::StreamError::Closed)
        }
    }
    fn blocking_read(&self, len: u64) -> Result<Vec<u8>, exports::wasi::io::streams::StreamError> {
        self.read(len)
    }
    fn subscribe(&self) -> exports::wasi::io::poll::Pollable {
        ClosedPoll::closed()
    }
}
impl exports::wasi::io::streams::GuestOutputStream for ClosedOutput {
    fn check_write(&self) -> Result<u64, exports::wasi::io::streams::StreamError> {
        self.console
            .as_ref()
            .ok_or(exports::wasi::io::streams::StreamError::Closed)?
            .check_write()
    }
    fn write(&self, contents: Vec<u8>) -> Result<(), exports::wasi::io::streams::StreamError> {
        self.console
            .as_ref()
            .ok_or(exports::wasi::io::streams::StreamError::Closed)?
            .write(contents)
    }
    fn blocking_flush(&self) -> Result<(), exports::wasi::io::streams::StreamError> {
        self.flush()
    }
    fn flush(&self) -> Result<(), exports::wasi::io::streams::StreamError> {
        self.console
            .as_ref()
            .ok_or(exports::wasi::io::streams::StreamError::Closed)?
            .flush()
    }
    fn subscribe(&self) -> exports::wasi::io::poll::Pollable {
        ClosedPoll::closed()
    }
}
