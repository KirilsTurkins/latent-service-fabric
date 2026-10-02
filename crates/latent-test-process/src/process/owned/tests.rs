use super::*;

#[test]
fn invalid_limits_fail_before_attempting_to_spawn_a_program() {
    let invalid = ProcessLimits {
        timeout: Duration::ZERO,
        ..ProcessLimits::default()
    };
    let result = OwnedProcess::spawn(Command::new("program-that-does-not-exist"), invalid);
    assert_eq!(result.err().unwrap().kind(), io::ErrorKind::InvalidInput);
}

#[tokio::test]
async fn aborting_a_reader_drops_the_pipe_without_waiting_for_inherited_writers() {
    use std::pin::Pin;
    use std::sync::atomic::{AtomicBool, Ordering};
    use std::task::{Context, Poll};
    use tokio::io::{AsyncRead, ReadBuf};

    struct Pipe(Arc<AtomicBool>);
    impl AsyncRead for Pipe {
        fn poll_read(
            self: Pin<&mut Self>,
            _: &mut Context<'_>,
            _: &mut ReadBuf<'_>,
        ) -> Poll<io::Result<()>> {
            Poll::Pending
        }
    }
    impl Drop for Pipe {
        fn drop(&mut self) {
            self.0.store(true, Ordering::SeqCst);
        }
    }
    let dropped = Arc::new(AtomicBool::new(false));
    let capture = Capture::new(32, Arc::new(Notify::new()));
    let reader = capture.spawn(Pipe(Arc::clone(&dropped)));
    tokio::task::yield_now().await;
    reader.abort();
    assert!(reader.await.unwrap_err().is_cancelled());
    assert!(dropped.load(Ordering::SeqCst));
    assert!(capture.snapshot().unwrap().is_empty());
}

#[cfg(target_os = "linux")]
fn shell(script: &str) -> Command {
    let mut command = Command::new("/bin/sh");
    command.args(["-c", script]);
    command
}

#[cfg(target_os = "linux")]
#[tokio::test]
async fn child_records_and_both_pipes_are_complete_after_wait() {
    let child = OwnedProcess::spawn(
        shell("printf 'ready\\n'; printf 'notice\\n' >&2"),
        ProcessLimits::default(),
    )
    .unwrap();
    let id = child.id();
    assert_eq!(child.wait_for_stdout_line().await.unwrap(), b"ready\n");
    let output = child.wait().await.unwrap();
    assert!(output.status.success());
    assert_eq!(output.stdout, b"ready\n");
    assert_eq!(output.stderr, b"notice\n");
    assert!(!std::path::Path::new(&format!("/proc/{id}")).exists());
}

#[cfg(target_os = "linux")]
#[tokio::test]
async fn overflowing_either_pipe_is_an_error_and_the_live_child_is_reaped() {
    for script in [
        "printf 12345; exec sleep 30",
        "printf 12345 >&2; exec sleep 30",
    ] {
        let limits = ProcessLimits {
            maximum_stdout_bytes: 4,
            maximum_stderr_bytes: 4,
            ..ProcessLimits::default()
        };
        let child = OwnedProcess::spawn(shell(script), limits).unwrap();
        let id = child.id();
        let error = child.wait().await.unwrap_err();
        assert_eq!(error.kind(), io::ErrorKind::InvalidData);
        assert!(!std::path::Path::new(&format!("/proc/{id}")).exists());
    }
}

#[cfg(target_os = "linux")]
#[tokio::test]
async fn lifetime_timeout_reaps_the_child_and_explicit_termination_retains_status() {
    let limits = ProcessLimits {
        timeout: Duration::from_millis(20),
        ..ProcessLimits::default()
    };
    let child = OwnedProcess::spawn(shell("exec sleep 30"), limits).unwrap();
    let id = child.id();
    assert_eq!(
        child.wait().await.unwrap_err().kind(),
        io::ErrorKind::TimedOut
    );
    assert!(!std::path::Path::new(&format!("/proc/{id}")).exists());

    let child = OwnedProcess::spawn(
        shell("printf 'ready\\n'; exec sleep 30"),
        ProcessLimits::default(),
    )
    .unwrap();
    let id = child.id();
    child.wait_for_stdout_line().await.unwrap();
    let output = child.terminate().await.unwrap();
    assert!(!output.status.success());
    assert_eq!(output.stdout, b"ready\n");
    assert!(!std::path::Path::new(&format!("/proc/{id}")).exists());
}

#[cfg(target_os = "linux")]
#[tokio::test]
async fn dropping_a_pending_wait_keeps_the_child_under_tokio_cleanup() {
    use std::future::Future;
    use std::task::{Context, Waker};

    let child = OwnedProcess::spawn(shell("exec sleep 30"), ProcessLimits::default()).unwrap();
    let id = child.id();
    let mut future = Box::pin(child.wait());
    assert!(future
        .as_mut()
        .poll(&mut Context::from_waker(Waker::noop()))
        .is_pending());
    drop(future);
    tokio::time::timeout(Duration::from_secs(2), async {
        while std::path::Path::new(&format!("/proc/{id}")).exists() {
            tokio::time::sleep(Duration::from_millis(5)).await;
        }
    })
    .await
    .expect("Tokio reaped the abandoned child");
}
