//! Identity-bound observations of the process retaining this probe itself.

use std::io;

use super::{ChildProcessResources, ProbeLimits, ProcessIdentity};

/// A measurement collector can sample its own real node process. This includes
/// fixed collector/client overhead; it is not an external child's observation.
/// Unlike a free PID lookup, the current process cannot be reaped/reused while
/// this method is executing. Forking invalidates the bound PID and is rejected.
pub struct CurrentProcessOwnerProbe {
    identity: ProcessIdentity,
    limits: ProbeLimits,
}

impl CurrentProcessOwnerProbe {
    pub fn bind(limits: ProbeLimits) -> io::Result<Self> {
        limits.validate()?;
        #[cfg(target_os = "linux")]
        {
            Ok(Self {
                identity: super::linux::identity(std::process::id(), limits)?,
                limits,
            })
        }
        #[cfg(not(target_os = "linux"))]
        Err(io::Error::new(
            io::ErrorKind::Unsupported,
            "owned process observations require Linux",
        ))
    }

    #[must_use]
    pub const fn identity(&self) -> ProcessIdentity {
        self.identity
    }

    pub fn capture(&self) -> io::Result<ChildProcessResources> {
        if std::process::id() != self.identity.process_id {
            return Err(io::Error::other(
                "resource probe belongs to another process",
            ));
        }
        #[cfg(target_os = "linux")]
        {
            for attempt in 1..=self.limits.maximum_attempts {
                match super::linux::capture(self.identity, self.limits, attempt) {
                    Ok(value) => return Ok(value),
                    Err(error)
                        if matches!(
                            error.kind(),
                            io::ErrorKind::NotFound | io::ErrorKind::Interrupted
                        ) && attempt < self.limits.maximum_attempts => {}
                    Err(error) => return Err(error),
                }
            }
            Err(io::Error::other("owned process observation unavailable"))
        }
        #[cfg(not(target_os = "linux"))]
        {
            let _ = self.limits;
            Err(io::Error::new(
                io::ErrorKind::Unsupported,
                "owned process observations require Linux",
            ))
        }
    }
}

#[cfg(all(test, target_os = "linux"))]
mod tests {
    use super::*;
    use std::process::{Child, Command, Stdio};
    use std::time::{Duration, Instant};

    struct Reaped(Child);
    impl Drop for Reaped {
        fn drop(&mut self) {
            let _ = self.0.kill();
            let _ = self.0.wait();
        }
    }

    #[test]
    fn own_sampling_has_stable_identity_and_does_not_count_its_directory_handle() {
        const NAME: &str = concat!(
            module_path!(),
            "::own_sampling_has_stable_identity_and_does_not_count_its_directory_handle"
        );
        const CHILD: &str = "LSF_CURRENT_PROCESS_PROBE_TEST";
        const MARKER: &str = "LSF_CURRENT_PROCESS_PROBE_MARKER";
        if std::env::var(CHILD).as_deref() != Ok(NAME) {
            let directory = tempfile::tempdir().unwrap();
            let marker = directory.path().join("completed");
            let mut child = Reaped(
                Command::new(std::env::current_exe().unwrap())
                    .args([
                        "--exact",
                        NAME.trim_start_matches("latent_testkit::"),
                        "--test-threads=1",
                    ])
                    .env(CHILD, NAME)
                    .env(MARKER, &marker)
                    .stdout(Stdio::null())
                    .stderr(Stdio::null())
                    .spawn()
                    .unwrap(),
            );
            let deadline = Instant::now() + Duration::from_secs(5);
            loop {
                if let Some(status) = child.0.try_wait().unwrap() {
                    assert!(status.success());
                    break;
                }
                assert!(
                    Instant::now() < deadline,
                    "current process probe child timed out"
                );
                std::thread::sleep(Duration::from_millis(10));
            }
            assert_eq!(std::fs::read(marker).unwrap(), b"completed");
            return;
        }
        let probe = CurrentProcessOwnerProbe::bind(ProbeLimits::default()).unwrap();
        let first = probe.capture().unwrap();
        let file = std::fs::File::open("/dev/null").unwrap();
        let second = probe.capture().unwrap();
        assert_eq!(first.identity, second.identity);
        assert_eq!(first.identity.process_id, std::process::id());
        assert!(first.process.open_file_descriptors.unwrap() > 0);
        assert_eq!(
            first.process.open_file_descriptors.unwrap() + 1,
            second.process.open_file_descriptors.unwrap()
        );
        drop(file);
        assert_eq!(
            probe.capture().unwrap().process.open_file_descriptors,
            first.process.open_file_descriptors
        );
        assert_eq!(first.task_count, first.process.thread_count.unwrap());
        assert_eq!(second.task_count, second.process.thread_count.unwrap());
        std::fs::write(std::env::var_os(MARKER).unwrap(), b"completed").unwrap();
    }
}
