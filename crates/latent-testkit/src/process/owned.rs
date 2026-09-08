mod capture;
#[cfg(test)]
mod tests;

use std::io;
use std::process::{Command, ExitStatus, Stdio};
use std::sync::Arc;
use std::time::Duration;

use tokio::process::Child;
use tokio::sync::Notify;
use tokio::task::JoinHandle;
use tokio::time::{timeout_at, Instant};

use super::CapturedProcess;
use capture::Capture;

const CLEANUP_TIMEOUT: Duration = Duration::from_secs(2);

/// Independent per-pipe byte ceilings and a total child lifetime.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ProcessLimits {
    pub maximum_stdout_bytes: usize,
    pub maximum_stderr_bytes: usize,
    pub timeout: Duration,
}

impl Default for ProcessLimits {
    fn default() -> Self {
        Self {
            maximum_stdout_bytes: 64 * 1024,
            maximum_stderr_bytes: 64 * 1024,
            timeout: Duration::from_secs(5),
        }
    }
}

impl ProcessLimits {
    pub fn validate(self) -> io::Result<()> {
        if self.maximum_stdout_bytes > 16 * 1024 * 1024
            || self.maximum_stderr_bytes > 16 * 1024 * 1024
            || self.timeout.is_zero()
            || self.timeout > Duration::from_mins(5)
        {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "invalid process limits",
            ));
        }
        Ok(())
    }
}

/// One child and two cancellable, bounded pipe readers.
///
/// Call from an I/O-enabled Tokio runtime. Explicit [`Self::wait`] or
/// [`Self::terminate`] reaps the child and joins readers. Dropping the owner aborts
/// readers and requests child termination through Tokio's `kill_on_drop`; it is
/// a fallback, not evidence that a successful reap has already happened.
pub struct OwnedProcess {
    child: Child,
    id: u32,
    status: Option<ExitStatus>,
    deadline: Instant,
    stdout: Capture,
    stderr: Capture,
    changed: Arc<Notify>,
    readers: [Option<JoinHandle<()>>; 2],
}

impl OwnedProcess {
    pub fn spawn(command: Command, limits: ProcessLimits) -> io::Result<Self> {
        limits.validate()?;
        tokio::runtime::Handle::try_current()
            .map_err(|_| io::Error::other("process owner requires a Tokio runtime"))?;
        let deadline = Instant::now() + limits.timeout;
        let mut command = tokio::process::Command::from(command);
        command
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .kill_on_drop(true);
        let mut child = command.spawn()?;
        let id = child
            .id()
            .ok_or_else(|| io::Error::other("missing child identity"))?;
        let changed = Arc::new(Notify::new());
        let stdout = Capture::new(limits.maximum_stdout_bytes, Arc::clone(&changed));
        let stderr = Capture::new(limits.maximum_stderr_bytes, Arc::clone(&changed));
        let output = child
            .stdout
            .take()
            .ok_or_else(|| io::Error::other("missing child stdout"))?;
        let errors = child
            .stderr
            .take()
            .ok_or_else(|| io::Error::other("missing child stderr"))?;
        let readers = [Some(stdout.spawn(output)), Some(stderr.spawn(errors))];
        Ok(Self {
            child,
            id,
            status: None,
            deadline,
            stdout,
            stderr,
            changed,
            readers,
        })
    }

    #[must_use]
    pub const fn id(&self) -> u32 {
        self.id
    }

    pub fn try_status(&mut self) -> io::Result<Option<ExitStatus>> {
        if Instant::now() >= self.deadline && self.status.is_none() {
            self.child.start_kill()?;
            return Err(expired());
        }
        if self.status.is_none() {
            self.status = self.child.try_wait()?;
        }
        Ok(self.status)
    }

    pub fn stdout_snapshot(&self) -> io::Result<Vec<u8>> {
        self.stdout.snapshot()
    }

    pub fn stderr_snapshot(&self) -> io::Result<Vec<u8>> {
        self.stderr.snapshot()
    }

    /// Waits for the first complete stdout record without consuming retained data.
    /// No newline before pipe closure is an error; output remains bounded.
    pub async fn wait_for_stdout_line(&self) -> io::Result<Vec<u8>> {
        loop {
            if Instant::now() >= self.deadline {
                return Err(expired());
            }
            let changed = self.changed.notified();
            tokio::pin!(changed);
            changed.as_mut().enable();
            self.stderr.check()?;
            if let Some(line) = self.stdout.line()? {
                return Ok(line);
            }
            timeout_at(self.deadline, changed)
                .await
                .map_err(|_| expired())?;
        }
    }

    pub async fn wait(mut self) -> io::Result<CapturedProcess> {
        let result = self.wait_inner().await;
        match result {
            Ok(status) => Ok(CapturedProcess {
                status,
                stdout: self.stdout.snapshot()?,
                stderr: self.stderr.snapshot()?,
            }),
            Err(error) => {
                self.cleanup().await?;
                Err(error)
            }
        }
    }

    /// Forces termination, reaps the child, and cancels/joins both pipe readers.
    /// A capture failure is still returned; termination never hides truncation.
    pub async fn terminate(mut self) -> io::Result<CapturedProcess> {
        self.cleanup().await?;
        Ok(CapturedProcess {
            status: self
                .status
                .ok_or_else(|| io::Error::other("child was not reaped"))?,
            stdout: self.stdout.snapshot()?,
            stderr: self.stderr.snapshot()?,
        })
    }

    async fn wait_inner(&mut self) -> io::Result<ExitStatus> {
        let notifications = Arc::clone(&self.changed);
        loop {
            if Instant::now() >= self.deadline {
                return Err(expired());
            }
            let changed = notifications.notified();
            tokio::pin!(changed);
            changed.as_mut().enable();
            self.stdout.check()?;
            self.stderr.check()?;
            if let Some(status) = self.status {
                self.join_readers(self.deadline).await?;
                return Ok(status);
            }
            tokio::select! {
                biased;
                () = &mut changed => {},
                status = self.child.wait() => self.status = Some(status?),
                () = tokio::time::sleep_until(self.deadline) => return Err(expired()),
            }
        }
    }

    async fn cleanup(&mut self) -> io::Result<()> {
        // Abort before waiting: inherited pipe writers cannot strand readers.
        for reader in self.readers.iter().flatten() {
            reader.abort();
        }
        let deadline = Instant::now() + CLEANUP_TIMEOUT;
        if self.status.is_none() {
            self.status = self.child.try_wait()?;
        }
        if self.status.is_none() {
            self.child.start_kill()?;
            self.status = Some(
                timeout_at(deadline, self.child.wait())
                    .await
                    .map_err(|_| {
                        io::Error::new(io::ErrorKind::TimedOut, "child reap deadline exceeded")
                    })??,
            );
        }
        self.join_readers(deadline).await
    }

    async fn join_readers(&mut self, deadline: Instant) -> io::Result<()> {
        for reader in &mut self.readers {
            if let Some(task) = reader {
                let result = timeout_at(deadline, &mut *task)
                    .await
                    .map_err(|_| expired())?;
                *reader = None;
                if result.is_err_and(|error| !error.is_cancelled()) {
                    return Err(io::Error::other("process reader task failed"));
                }
            }
        }
        self.stdout.check()?;
        self.stderr.check()
    }
}

impl Drop for OwnedProcess {
    fn drop(&mut self) {
        for reader in self.readers.iter().flatten() {
            reader.abort();
        }
        // Child::drop owns the kill-on-drop request and Tokio's reaping fallback.
    }
}

fn expired() -> io::Error {
    io::Error::new(
        io::ErrorKind::TimedOut,
        "process lifetime or output deadline exceeded",
    )
}
