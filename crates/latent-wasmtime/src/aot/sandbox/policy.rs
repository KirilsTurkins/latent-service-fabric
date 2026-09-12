use std::collections::BTreeMap;

use latent_core::{PlatformError, PlatformErrorCode};
use seccompiler::{
    BpfProgram, SeccompAction, SeccompCmpArgLen, SeccompCmpOp, SeccompCondition, SeccompFilter,
    SeccompRule, TargetArch,
};

use super::failure;

/// Fixed policy, never supplied by a request. Empty syscall rule lists mean
/// unconditional permission in seccompiler; every descriptor operation instead
/// uses an explicit list of alternatives. All other syscalls return EPERM.
pub(super) fn build() -> Result<BpfProgram, PlatformError> {
    let mut rules = BTreeMap::new();
    for syscall in [
        libc::SYS_brk,
        libc::SYS_munmap,
        libc::SYS_rt_sigaction,
        libc::SYS_rt_sigprocmask,
        libc::SYS_rt_sigreturn,
        libc::SYS_sigaltstack,
        libc::SYS_sched_yield,
        libc::SYS_getpid,
        libc::SYS_getppid,
        libc::SYS_gettid,
        libc::SYS_exit,
        libc::SYS_exit_group,
    ] {
        rules.insert(syscall, Vec::new());
    }
    for syscall in [libc::SYS_read, libc::SYS_readv] {
        rules.insert(syscall, alternatives(0, &[0])?);
    }
    for syscall in [libc::SYS_write, libc::SYS_writev] {
        rules.insert(syscall, alternatives(0, &[1, 2])?);
    }
    for syscall in [libc::SYS_close, libc::SYS_fstat] {
        rules.insert(syscall, alternatives(0, &[0, 1, 2])?);
    }
    // Permit only private anonymous memory with a zero offset and no executable
    // protection. No MAP_FIXED, file mappings, pkeys, memfd or remapping syscall.
    rules.insert(
        libc::SYS_mmap,
        vec![rule(vec![
            condition(2, SeccompCmpOp::MaskedEq(!3_u64), 0)?,
            condition(3, SeccompCmpOp::Eq, 0x22)?,
            // The kernel consumes fd as a signed 32-bit int; libc may leave
            // either zero-extended or sign-extended -1 in the argument register.
            SeccompCondition::new(
                4,
                SeccompCmpArgLen::Dword,
                SeccompCmpOp::Eq,
                u64::from(u32::MAX),
            )
            .map_err(|_| invalid())?,
            condition(5, SeccompCmpOp::Eq, 0)?,
        ])?],
    );
    rules.insert(
        libc::SYS_mprotect,
        vec![rule(vec![condition(
            2,
            SeccompCmpOp::MaskedEq(!3_u64),
            0,
        )?])?],
    );
    rules.insert(libc::SYS_madvise, alternatives(2, &[4, 8])?);
    // Futex operations are private to this process. No wake across processes or
    // PI/requeue operations are needed by a single-threaded compiler.
    rules.insert(libc::SYS_futex, alternatives(1, &[128, 129, 137])?);
    rules.insert(libc::SYS_clock_gettime, alternatives(0, &[0, 1])?);
    rules.insert(
        libc::SYS_getrandom,
        vec![rule(vec![
            condition(1, SeccompCmpOp::Le, 256)?,
            condition(2, SeccompCmpOp::MaskedEq(!1_u64), 0)?,
        ])?],
    );
    let program: BpfProgram = SeccompFilter::new(
        rules,
        SeccompAction::Errno(1),
        SeccompAction::Allow,
        TargetArch::x86_64,
    )
    .map_err(|_| invalid())?
    .try_into()
    .map_err(|_| invalid())?;
    if program.len() > 1024 {
        return Err(invalid());
    }
    Ok(program)
}

fn alternatives(argument: u8, values: &[u64]) -> Result<Vec<SeccompRule>, PlatformError> {
    values
        .iter()
        .map(|value| rule(vec![condition(argument, SeccompCmpOp::Eq, *value)?]))
        .collect()
}

fn condition(
    argument: u8,
    comparison: SeccompCmpOp,
    value: u64,
) -> Result<SeccompCondition, PlatformError> {
    SeccompCondition::new(argument, SeccompCmpArgLen::Qword, comparison, value)
        .map_err(|_| invalid())
}

fn rule(conditions: Vec<SeccompCondition>) -> Result<SeccompRule, PlatformError> {
    SeccompRule::new(conditions).map_err(|_| invalid())
}

fn invalid() -> PlatformError {
    failure(
        PlatformErrorCode::Internal,
        "aot-fixed-seccomp-policy-invalid",
    )
}
