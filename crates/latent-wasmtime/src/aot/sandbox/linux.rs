use std::{
    fs::{self, File},
    io::Read,
    os::unix::fs::FileTypeExt,
};

use landlock::{
    Access, AccessFs, CompatLevel, Compatible, RestrictionStatus, Ruleset, RulesetAttr,
    RulesetStatus, ABI,
};
use latent_core::{PlatformError, PlatformErrorCode};
use rustix::process::{self, Resource, Rlimit, Signal};

use super::{failure, policy, SandboxLimits};

pub(super) fn bootstrap(limits: SandboxLimits, parent_pid: u32) -> Result<(), PlatformError> {
    launch_limits(limits, parent_pid)?;
    inventory(limits.maximum_fds)?;
    personality()?;
    Ok(())
}

pub(super) fn prepare_launch(
    limits: SandboxLimits,
    parent_pid: u32,
    reexec_arguments: Option<&[std::ffi::OsString]>,
) -> Result<(), PlatformError> {
    use std::os::unix::process::CommandExt as _;

    launch_limits(limits, parent_pid)?;
    if let Some(arguments) = reexec_arguments {
        // With no kept descriptors this uses one close_range(CLOEXEC). Disable
        // proc iteration: if that syscall is blocked, the crate's numeric
        // fallback is at most 1021 descriptors under our <=64 NOFILE ceiling.
        // The API intentionally ignores syscall errors; the next image MUST
        // check strict inventory instead of trusting the marker as success.
        close_fds::CloseFdsBuilder::new()
            .allow_filesystem(false)
            .cloexecfrom(3);
        let _error = std::process::Command::new("/proc/self/exe")
            .env_clear()
            .args(arguments)
            .exec();
        return Err(denied("aot-worker-reexec-failed"));
    }
    inventory(limits.maximum_fds)?;
    personality()?;
    Ok(())
}

fn launch_limits(limits: SandboxLimits, parent_pid: u32) -> Result<(), PlatformError> {
    check_parent(parent_pid)?;
    single_thread()?;
    process::set_parent_process_death_signal(Some(Signal::KILL))
        .map_err(|_| denied("aot-parent-death-guard-unavailable"))?;
    // Catch a parent exiting between the first check and PR_SET_PDEATHSIG.
    check_parent(parent_pid)?;
    for (resource, bound) in limits_list(limits) {
        let inherited = process::getrlimit(resource).maximum.unwrap_or(u64::MAX);
        let actual = bound.min(inherited);
        process::setrlimit(
            resource,
            Rlimit {
                current: Some(actual),
                maximum: Some(actual),
            },
        )
        .map_err(|_| denied("aot-resource-limit-unavailable"))?;
    }
    verify_limits(limits)?;
    rustix::thread::set_no_new_privs(true)
        .map_err(|_| denied("aot-no-new-privileges-unavailable"))?;
    Ok(())
}

pub(super) fn enter(limits: SandboxLimits, parent_pid: u32) -> Result<(), PlatformError> {
    // Engine initialization is trusted, but may not change these prerequisites.
    check_parent(parent_pid)?;
    single_thread()?;
    inventory(limits.maximum_fds)?;
    personality()?;
    verify_limits(limits)?;
    if process::parent_process_death_signal()
        .map_err(|_| denied("aot-parent-death-guard-unavailable"))?
        != Some(Signal::KILL)
        || !rustix::thread::no_new_privs()
            .map_err(|_| denied("aot-no-new-privileges-unavailable"))?
    {
        return Err(denied("aot-bootstrap-state-changed"));
    }
    let filter = policy::build()?;
    // NotDumpable changes /proc/self file ownership to root, so an unprivileged
    // process must finish its final inventory/personality reads first. The
    // parent's executable authentication and trusted engine setup are also
    // complete. No untrusted Wasm has been read, and none can be read until all
    // enforcement succeeds. Verify through prctl, without reopening /proc.
    process::set_dumpable_behavior(process::DumpableBehavior::NotDumpable)
        .map_err(|_| denied("aot-dump-protection-unavailable"))?;
    if process::dumpable_behavior().map_err(|_| denied("aot-dump-protection-unavailable"))?
        != process::DumpableBehavior::NotDumpable
    {
        return Err(denied("aot-dump-protection-unavailable"));
    }
    let status = Ruleset::default()
        .set_compatibility(CompatLevel::HardRequirement)
        .handle_access(AccessFs::from_all(ABI::V3))
        .map_err(|_| unsupported())?
        .create()
        .map_err(|_| unsupported())?
        .restrict_self()
        .map_err(|_| unsupported())?;
    if !matches!(
        status,
        RestrictionStatus {
            ruleset: RulesetStatus::FullyEnforced,
            no_new_privs: true,
            ..
        }
    ) {
        return Err(unsupported());
    }
    // No more filesystem reads, privilege changes or thread creation occur.
    // The installation library is safe Rust API; it checks the kernel result.
    seccompiler::apply_filter(&filter)
        .map_err(|_| denied("aot-seccomp-enforcement-unavailable"))?;
    Ok(())
}

fn limits_list(limits: SandboxLimits) -> [(Resource, u64); 6] {
    [
        (Resource::As, limits.address_space_bytes),
        (Resource::Cpu, limits.cpu_seconds),
        (Resource::Stack, limits.stack_bytes),
        (Resource::Nofile, limits.maximum_fds),
        (Resource::Core, 0),
        (Resource::Fsize, 0),
    ]
}

fn verify_limits(limits: SandboxLimits) -> Result<(), PlatformError> {
    for (resource, bound) in limits_list(limits) {
        let actual = process::getrlimit(resource);
        if actual.current.is_none_or(|value| value > bound)
            || actual.maximum.is_none_or(|value| value > bound)
        {
            return Err(denied("aot-resource-limit-changed"));
        }
    }
    Ok(())
}

fn check_parent(expected: u32) -> Result<(), PlatformError> {
    let actual = process::getppid().and_then(|pid| u32::try_from(pid.as_raw_pid()).ok());
    if actual != Some(expected) {
        return Err(denied("aot-parent-identity-changed"));
    }
    Ok(())
}

fn single_thread() -> Result<(), PlatformError> {
    let mut entries =
        fs::read_dir("/proc/self/task").map_err(|_| denied("aot-process-inventory-unavailable"))?;
    match (entries.next(), entries.next()) {
        (Some(Ok(_)), None) => Ok(()),
        _ => Err(denied("aot-sandbox-requires-one-thread")),
    }
}

fn inventory(maximum_fds: u64) -> Result<(), PlatformError> {
    let maximum =
        usize::try_from(maximum_fds).map_err(|_| denied("aot-descriptor-inventory-limit"))?;
    let mut numbers = Vec::with_capacity(maximum);
    {
        let entries = fs::read_dir("/proc/self/fd")
            .map_err(|_| denied("aot-process-inventory-unavailable"))?;
        for entry in entries {
            if numbers.len() == maximum {
                return Err(denied("aot-descriptor-inventory-limit"));
            }
            let name = entry
                .map_err(|_| denied("aot-process-inventory-unavailable"))?
                .file_name();
            let number = name
                .to_str()
                .filter(|name| name.len() <= 10 && name.bytes().all(|byte| byte.is_ascii_digit()))
                .and_then(|name| name.parse::<u32>().ok())
                .ok_or_else(|| denied("aot-descriptor-inventory-invalid"))?;
            numbers.push(number);
        }
    }
    // The iterator's own directory descriptor is now closed, before inspection.
    let mut standard = 0_u8;
    for number in numbers {
        let path = format!("/proc/self/fd/{number}");
        let metadata = match fs::metadata(path) {
            Ok(value) => value,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound && number > 2 => continue,
            Err(_) => return Err(denied("aot-descriptor-inventory-invalid")),
        };
        if number > 2 || !metadata.file_type().is_fifo() {
            return Err(denied("aot-sandbox-requires-only-three-pipes"));
        }
        let info = bounded_text(&format!("/proc/self/fdinfo/{number}"), 512)?;
        let flags = info
            .lines()
            .find_map(|line| line.strip_prefix("flags:"))
            .and_then(|value| u32::from_str_radix(value.trim(), 8).ok())
            .ok_or_else(|| denied("aot-descriptor-inventory-invalid"))?;
        let expected = u32::from(number != 0);
        if flags & 3 != expected {
            return Err(denied("aot-pipe-direction-invalid"));
        }
        standard |= 1 << number;
    }
    if standard != 7 {
        return Err(denied("aot-sandbox-requires-only-three-pipes"));
    }
    Ok(())
}

fn personality() -> Result<(), PlatformError> {
    let text = bounded_text("/proc/self/personality", 32)?;
    let flags =
        u32::from_str_radix(text.trim(), 16).map_err(|_| denied("aot-personality-invalid"))?;
    if flags & 0x0040_0000 != 0 {
        return Err(denied("aot-read-implies-execute-forbidden"));
    }
    Ok(())
}

fn bounded_text(path: &str, maximum: usize) -> Result<String, PlatformError> {
    let mut bytes = Vec::with_capacity(maximum + 1);
    File::open(path)
        .map_err(|_| denied("aot-process-inventory-unavailable"))?
        .take((maximum + 1) as u64)
        .read_to_end(&mut bytes)
        .map_err(|_| denied("aot-process-inventory-unavailable"))?;
    if bytes.len() > maximum {
        return Err(denied("aot-process-inventory-limit"));
    }
    String::from_utf8(bytes).map_err(|_| denied("aot-process-inventory-invalid"))
}

fn denied(reason: &'static str) -> PlatformError {
    failure(PlatformErrorCode::PermissionDenied, reason)
}

fn unsupported() -> PlatformError {
    failure(
        PlatformErrorCode::IncompatibleContract,
        "aot-landlock-abi3-enforcement-unavailable",
    )
}
