use std::fs::{self, File, OpenOptions};
use std::future::Future;
use std::io::{Read, Write};
use std::path::Path;
use std::sync::Arc;
use std::task::{Context, Poll, Wake, Waker};

use serde::Serialize;

use super::Result;

pub(super) fn read(path: &Path, maximum: usize) -> Result<Vec<u8>> {
    let before = fs::symlink_metadata(path).map_err(|_| "input-metadata")?;
    if !before.is_file() || before.len() > maximum as u64 {
        return Err("input-bound-or-type");
    }
    let file = File::open(path).map_err(|_| "input-open")?;
    let actual = file.metadata().map_err(|_| "input-metadata")?;
    if !actual.is_file() || actual.len() > maximum as u64 {
        return Err("input-bound-or-type");
    }
    let mut bytes = Vec::with_capacity(usize::try_from(actual.len()).map_err(|_| "input-size")?);
    file.take(maximum as u64 + 1)
        .read_to_end(&mut bytes)
        .map_err(|_| "input-read")?;
    if bytes.len() > maximum || bytes.len() as u64 != actual.len() {
        return Err("input-size-changed");
    }
    Ok(bytes)
}

pub(super) fn write(path: &Path, bytes: &[u8]) -> Result<()> {
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)
        .map_err(|_| "output-create")?;
    file.write_all(bytes).map_err(|_| "output-write")?;
    file.sync_all().map_err(|_| "output-sync")
}

pub(super) fn emit(value: &impl Serialize) -> Result<()> {
    let bytes = serde_json::to_vec(value).map_err(|_| "result-encode")?;
    if bytes.len() > 16 * 1024 {
        return Err("result-bound");
    }
    let mut output = std::io::stdout().lock();
    output.write_all(&bytes).map_err(|_| "stdout-write")?;
    output.write_all(b"\n").map_err(|_| "stdout-write")?;
    output.flush().map_err(|_| "stdout-flush")
}

struct NoWake;
impl Wake for NoWake {
    fn wake(self: Arc<Self>) {}
}

/// The concrete directory ports do synchronous I/O and complete on their first
/// poll. Reject unexpected suspension rather than inventing a runtime or wait.
pub(super) fn immediate<F: Future>(future: F) -> Result<F::Output> {
    let waker = Waker::from(Arc::new(NoWake));
    let mut context = Context::from_waker(&waker);
    match std::pin::pin!(future).as_mut().poll(&mut context) {
        Poll::Ready(value) => Ok(value),
        Poll::Pending => Err("unexpected-directory-suspension"),
    }
}
