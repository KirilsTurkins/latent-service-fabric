//! Fixed-pipe protocol; no per-pipe helper threads or unbounded diagnostics.

use super::super::{error, exhausted};
use super::AotCompilationJob;
use latent_core::{PlatformError, PlatformErrorCode};
use sha2::{Digest, Sha256};
use std::{fs::File, io::Read, path::Path};

const MAX_EXECUTABLE_BYTES: u64 = 512 * 1024 * 1024;
pub(super) fn failed() -> PlatformError {
    error(PlatformErrorCode::Unavailable, "aot-compiler-failed")
}
pub(super) fn supported() -> Result<(), PlatformError> {
    if cfg!(all(target_os = "linux", target_arch = "x86_64")) {
        Ok(())
    } else {
        Err(error(
            PlatformErrorCode::IncompatibleContract,
            "aot-sandbox-platform-unsupported",
        ))
    }
}
pub(super) fn hash_executable(
    path: &Path,
    mut check: impl FnMut() -> Result<(), PlatformError>,
) -> Result<[u8; 32], PlatformError> {
    let mut file = File::open(path).map_err(|_| failed())?;
    let metadata = file.metadata().map_err(|_| failed())?;
    if !metadata.is_file() || metadata.len() == 0 || metadata.len() > MAX_EXECUTABLE_BYTES {
        return Err(exhausted());
    }
    let mut bytes = [0; 16 * 1024];
    let mut digest = Sha256::new();
    let mut total = 0_u64;
    loop {
        check()?;
        let read = file.read(&mut bytes).map_err(|_| failed())?;
        if read == 0 {
            break;
        }
        total = total.checked_add(read as u64).ok_or_else(exhausted)?;
        if total > MAX_EXECUTABLE_BYTES {
            return Err(exhausted());
        }
        digest.update(&bytes[..read]);
    }
    if total != metadata.len() {
        return Err(rejected("aot-executable-length-changed"));
    }
    Ok(digest.finalize().into())
}

// Fixed stage names distinguish independent trust checks without exposing paths,
// source bytes, digests, child diagnostics, or authentication material.
fn rejected(reason: &'static str) -> PlatformError {
    error(PlatformErrorCode::PermissionDenied, reason)
}

pub(super) fn compile(job: &AotCompilationJob, input: &[u8]) -> Result<Vec<u8>, PlatformError> {
    #[cfg(all(target_os = "linux", target_arch = "x86_64"))]
    {
        linux::compile(job, input)
    }
    #[cfg(not(all(target_os = "linux", target_arch = "x86_64")))]
    {
        let _ = (job, input);
        supported()?;
        Err(failed())
    }
}

#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
mod linux {
    use super::{
        exhausted, failed, hash_executable, rejected, AotCompilationJob, PlatformError, Read,
    };
    use crate::aot::protocol;
    use rustix::fs::{fcntl_getfl, fcntl_setfl, OFlags};
    use std::{
        io::{self, Write},
        os::fd::AsFd,
        process::{Child, ChildStderr, ChildStdin, ChildStdout, Command, Stdio},
        time::Duration,
    };

    struct ChildOwner {
        child: Child,
        reaped: bool,
    }
    impl Drop for ChildOwner {
        fn drop(&mut self) {
            if !self.reaped {
                // Retain the complete outer job reservation through actual reap,
                // even if termination or a caller's shutdown deadline is late.
                let _ = self.child.kill();
                loop {
                    match self.child.wait() {
                        Err(error) if error.kind() == io::ErrorKind::Interrupted => {}
                        _ => break,
                    }
                }
            }
        }
    }
    struct Pipes {
        input: Option<ChildStdin>,
        output: ChildStdout,
        diagnostics: ChildStderr,
        diagnostic_bytes: usize,
    }
    impl Pipes {
        fn diagnostics(&mut self) -> Result<(), PlatformError> {
            let mut bytes = [0; 4096];
            match self.diagnostics.read(&mut bytes) {
                Ok(count) => {
                    self.diagnostic_bytes += count;
                    if self.diagnostic_bytes > 16 * 1024 {
                        return Err(exhausted());
                    }
                    Ok(())
                }
                Err(error)
                    if matches!(
                        error.kind(),
                        io::ErrorKind::WouldBlock | io::ErrorKind::Interrupted
                    ) =>
                {
                    Ok(())
                }
                Err(_) => Err(failed()),
            }
        }
        fn write(
            &mut self,
            mut bytes: &[u8],
            job: &AotCompilationJob,
        ) -> Result<(), PlatformError> {
            while !bytes.is_empty() {
                job.check_control()?;
                self.diagnostics()?;
                let amount = bytes.len().min(64 * 1024);
                match self
                    .input
                    .as_mut()
                    .ok_or_else(failed)?
                    .write(&bytes[..amount])
                {
                    Ok(0) => return Err(failed()),
                    Ok(written) => bytes = &bytes[written..],
                    Err(error) if error.kind() == io::ErrorKind::WouldBlock => pause(),
                    Err(error) if error.kind() == io::ErrorKind::Interrupted => {}
                    Err(_) => return Err(failed()),
                }
            }
            Ok(())
        }
        fn read(
            &mut self,
            mut bytes: &mut [u8],
            job: &AotCompilationJob,
        ) -> Result<(), PlatformError> {
            while !bytes.is_empty() {
                job.check_control()?;
                self.diagnostics()?;
                let amount = bytes.len().min(64 * 1024);
                match self.output.read(&mut bytes[..amount]) {
                    Ok(0) => return Err(failed()),
                    Ok(read) => bytes = &mut bytes[read..],
                    Err(error) if error.kind() == io::ErrorKind::WouldBlock => pause(),
                    Err(error) if error.kind() == io::ErrorKind::Interrupted => {}
                    Err(_) => return Err(failed()),
                }
            }
            Ok(())
        }
    }
    fn pause() {
        std::thread::sleep(Duration::from_millis(1));
    }
    fn nonblocking(fd: impl AsFd) -> Result<(), PlatformError> {
        let flags = fcntl_getfl(&fd).map_err(|_| failed())?;
        fcntl_setfl(&fd, flags | OFlags::NONBLOCK).map_err(|_| failed())
    }
    pub(super) fn compile(job: &AotCompilationJob, input: &[u8]) -> Result<Vec<u8>, PlatformError> {
        job.check()?;
        let state = &job.state;
        let limits = state.limits;
        let arguments = protocol::WorkerOptions {
            parent_pid: std::process::id(),
            sandbox: limits.sandbox,
            maximum_input_bytes: limits.maximum_component_bytes,
            maximum_output_bytes: limits.compiler.maximum_output_bytes,
        }
        .arguments()?;
        let child = Command::new(&state.executable)
            .env_clear()
            .current_dir("/")
            .args(arguments)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .map_err(|_| failed())?;
        let mut owner = ChildOwner {
            child,
            reaped: false,
        };
        let mut pipes = Pipes {
            input: Some(owner.child.stdin.take().ok_or_else(failed)?),
            output: owner.child.stdout.take().ok_or_else(failed)?,
            diagnostics: owner.child.stderr.take().ok_or_else(failed)?,
            diagnostic_bytes: 0,
        };
        nonblocking(pipes.input.as_ref().ok_or_else(failed)?)?;
        nonblocking(&pipes.output)?;
        nonblocking(&pipes.diagnostics)?;
        // The controlled child blocks before sandbox bootstrap until this header
        // arrives. /proc identifies the actual unreaped process's executable,
        // closing a path replacement between configuration hashing and spawn.
        let running = std::path::PathBuf::from(format!("/proc/{}/exe", owner.child.id()));
        if hash_executable(&running, || job.check_control())? != state.compiler_digest {
            return Err(rejected("aot-running-executable-mismatch"));
        }
        let bootstrap_length = u32::try_from(state.bootstrap.len()).map_err(|_| exhausted())?;
        pipes.write(&bootstrap_length.to_le_bytes(), job)?;
        pipes.write(&state.bootstrap, job)?;
        let mut ready = [0; protocol::READY_BYTES];
        pipes.read(&mut ready, job)?;
        if ready != protocol::readiness(state.profile.engine_compatibility()) {
            return Err(rejected("aot-worker-readiness-mismatch"));
        }
        // Only the approved fully isolated child now receives untrusted Wasm.
        pipes.write(&(input.len() as u64).to_le_bytes(), job)?;
        pipes.write(input, job)?;
        drop(pipes.input.take());
        let mut length = [0; 8];
        pipes.read(&mut length, job)?;
        let length = usize::try_from(u64::from_le_bytes(length)).map_err(|_| exhausted())?;
        if length == 0 || length > limits.compiler.maximum_output_bytes {
            return Err(exhausted());
        }
        let mut output = Vec::new();
        output.try_reserve_exact(length).map_err(|_| exhausted())?;
        if output.capacity() > limits.compiler.maximum_output_bytes {
            return Err(exhausted());
        }
        output.resize(length, 0);
        pipes.read(&mut output, job)?;
        // Exact framing includes EOF and successful exit. Never sign a prefix
        // while an approved process is still alive or has emitted extra bytes.
        let mut eof = false;
        loop {
            job.check_control()?;
            pipes.diagnostics()?;
            let mut extra = [0; 1];
            match pipes.output.read(&mut extra) {
                Ok(0) => eof = true,
                Ok(_) => return Err(rejected("aot-worker-trailing-output")),
                Err(error)
                    if matches!(
                        error.kind(),
                        io::ErrorKind::WouldBlock | io::ErrorKind::Interrupted
                    ) => {}
                Err(_) => return Err(failed()),
            }
            if let Some(status) = owner.child.try_wait().map_err(|_| failed())? {
                owner.reaped = true;
                if !status.success() {
                    return Err(failed());
                }
                if eof {
                    break;
                }
            }
            pause();
        }
        job.check()?;
        Ok(output)
    }
}
