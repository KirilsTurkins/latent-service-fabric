//! The compiler child's one-way, single-threaded Linux sandbox boundary.
//!
//! Bootstrap and entry are exclusively for a disposable compiler process. A
//! failure can leave irreversible restrictions installed; the caller must exit,
//! never continue compiling or report readiness. No untrusted component bytes
//! may be consumed before `PreparedSandbox::enter` succeeds.

use std::{marker::PhantomData, rc::Rc};

use latent_core::{PlatformError, PlatformErrorCode};
use serde::{Deserialize, Serialize};

#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
#[path = "sandbox/linux.rs"]
mod linux;
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
#[path = "sandbox/policy.rs"]
mod policy;
#[cfg(test)]
#[path = "sandbox/tests.rs"]
#[allow(
    dead_code,
    unused_imports,
    reason = "the harness-free acceptance target includes this source without libtest collection"
)]
mod tests;

pub(crate) const PROFILE_ID: &str = "lsf-linux-x86_64-landlock3-seccomp-v1";

/// Hard upper bounds for a single compiler process, including trusted setup.
/// Address space includes executable mappings, heap, input and output buffers.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SandboxLimits {
    pub address_space_bytes: u64,
    pub cpu_seconds: u64,
    pub stack_bytes: u64,
    pub maximum_fds: u64,
}

impl Default for SandboxLimits {
    fn default() -> Self {
        Self {
            address_space_bytes: 512 * 1024 * 1024,
            cpu_seconds: 30,
            stack_bytes: 8 * 1024 * 1024,
            maximum_fds: 16,
        }
    }
}

impl SandboxLimits {
    pub fn validate(self) -> Result<Self, PlatformError> {
        if !(64 * 1024 * 1024..=4 * 1024 * 1024 * 1024).contains(&self.address_space_bytes)
            || !(1..=300).contains(&self.cpu_seconds)
            || !(1024 * 1024..=64 * 1024 * 1024).contains(&self.stack_bytes)
            || self.stack_bytes > self.address_space_bytes
            || !(8..=64).contains(&self.maximum_fds)
        {
            return Err(failure(
                PlatformErrorCode::InvalidArgument,
                "invalid-aot-sandbox-limits",
            ));
        }
        Ok(self)
    }
}

/// Bootstrap ownership cannot cross threads: Landlock and seccomp affect the
/// calling thread, and the process must remain single-threaded through entry.
#[derive(Debug)]
pub(crate) struct PreparedSandbox {
    limits: SandboxLimits,
    parent_pid: u32,
    _thread: PhantomData<Rc<()>>,
}

/// This affine value is constructed only after full kernel enforcement.
/// Dropping it cannot undo the sandbox, and it cannot be sent to another thread.
#[derive(Debug)]
pub(crate) struct EnforcedSandbox {
    _thread: PhantomData<Rc<()>>,
}

pub(crate) fn bootstrap(
    limits: SandboxLimits,
    parent_pid: u32,
) -> Result<PreparedSandbox, PlatformError> {
    let limits = limits.validate()?;
    if parent_pid == 0 || parent_pid > i32::MAX as u32 {
        return Err(failure(
            PlatformErrorCode::InvalidArgument,
            "invalid-aot-parent-pid",
        ));
    }
    #[cfg(all(target_os = "linux", target_arch = "x86_64"))]
    {
        linux::bootstrap(limits, parent_pid)?;
        Ok(PreparedSandbox {
            limits,
            parent_pid,
            _thread: PhantomData,
        })
    }
    #[cfg(not(all(target_os = "linux", target_arch = "x86_64")))]
    {
        let _ = limits;
        Err(failure(
            PlatformErrorCode::IncompatibleContract,
            "aot-sandbox-platform-unsupported",
        ))
    }
}

impl PreparedSandbox {
    pub(crate) fn enter(self) -> Result<EnforcedSandbox, PlatformError> {
        #[cfg(all(target_os = "linux", target_arch = "x86_64"))]
        {
            linux::enter(self.limits, self.parent_pid)?;
            Ok(EnforcedSandbox {
                _thread: PhantomData,
            })
        }
        #[cfg(not(all(target_os = "linux", target_arch = "x86_64")))]
        {
            let _ = (self.limits, self.parent_pid);
            Err(failure(
                PlatformErrorCode::IncompatibleContract,
                "aot-sandbox-platform-unsupported",
            ))
        }
    }
}

impl EnforcedSandbox {
    #[must_use]
    #[allow(
        clippy::unused_self,
        reason = "the receiver requires possession of the affine enforced-sandbox proof"
    )]
    pub(crate) fn profile_id(&self) -> &'static str {
        PROFILE_ID
    }
}

fn failure(code: PlatformErrorCode, reason: &'static str) -> PlatformError {
    PlatformError {
        code,
        message: reason.to_owned(),
        retryable: false,
        details: Vec::new(),
    }
}

/// Exact generated policy for kernel acceptance probes in a test-only process.
/// Serialization exposes no enforcement capability or production worker mode.
#[cfg(all(test, target_os = "linux", target_arch = "x86_64"))]
#[allow(dead_code)] // Also included by the separate harness=false acceptance target.
pub(crate) fn probe_policy_bytes() -> Result<Vec<u8>, PlatformError> {
    let program = policy::build()?;
    let mut bytes = Vec::with_capacity(program.len() * 8);
    for instruction in program {
        bytes.extend_from_slice(&instruction.code.to_le_bytes());
        bytes.extend_from_slice(&[instruction.jt, instruction.jf]);
        bytes.extend_from_slice(&instruction.k.to_le_bytes());
    }
    Ok(bytes)
}
