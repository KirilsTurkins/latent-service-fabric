//! Portable process resource snapshots with richer Linux `/proc` probes.

use std::io;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ProcessResources {
    pub process_id: u32,
    pub resident_memory_bytes: Option<u64>,
    pub thread_count: Option<u64>,
    pub open_file_descriptors: Option<u64>,
    pub socket_count: Option<u64>,
}

pub trait ResourceProbe: Send + Sync {
    fn capture(&self) -> io::Result<ProcessResources>;
}

#[derive(Debug, Clone, Copy, Default)]
pub struct CurrentProcessProbe;

impl ResourceProbe for CurrentProcessProbe {
    fn capture(&self) -> io::Result<ProcessResources> {
        capture_current_process()
    }
}

#[cfg(target_os = "linux")]
fn capture_current_process() -> io::Result<ProcessResources> {
    let status = std::fs::read_to_string("/proc/self/status")?;
    let resident_memory_bytes = status_value(&status, "VmRSS:").and_then(kibibytes_to_bytes);
    let thread_count = status_value(&status, "Threads:");
    let mut open_file_descriptors = 0_u64;
    let mut socket_count = 0_u64;
    for entry in std::fs::read_dir("/proc/self/fd")? {
        let entry = entry?;
        open_file_descriptors = open_file_descriptors.saturating_add(1);
        if std::fs::read_link(entry.path())
            .ok()
            .is_some_and(|target| target.to_string_lossy().starts_with("socket:["))
        {
            socket_count = socket_count.saturating_add(1);
        }
    }

    Ok(ProcessResources {
        process_id: std::process::id(),
        resident_memory_bytes,
        thread_count,
        open_file_descriptors: Some(open_file_descriptors),
        socket_count: Some(socket_count),
    })
}

#[cfg(not(target_os = "linux"))]
fn capture_current_process() -> io::Result<ProcessResources> {
    Ok(ProcessResources {
        process_id: std::process::id(),
        resident_memory_bytes: None,
        thread_count: None,
        open_file_descriptors: None,
        socket_count: None,
    })
}

#[cfg(target_os = "linux")]
fn status_value(status: &str, key: &str) -> Option<u64> {
    status.lines().find_map(|line| {
        line.strip_prefix(key)
            .and_then(|value| value.split_whitespace().next())
            .and_then(|value| value.parse().ok())
    })
}

#[cfg(target_os = "linux")]
fn kibibytes_to_bytes(value: u64) -> Option<u64> {
    value.checked_mul(1024)
}

#[cfg(test)]
mod tests {
    use super::{CurrentProcessProbe, ResourceProbe};

    #[test]
    fn captures_the_current_process_identity() {
        let resources = CurrentProcessProbe.capture().expect("process resources");
        assert_eq!(resources.process_id, std::process::id());
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn parses_linux_status_values() {
        let status = "Name:\ttest\nVmRSS:\t12 kB\nThreads:\t3\n";
        assert_eq!(super::status_value(status, "VmRSS:"), Some(12));
        assert_eq!(super::status_value(status, "Threads:"), Some(3));
    }
}
