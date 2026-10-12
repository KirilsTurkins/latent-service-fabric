use std::io;

use crate::process::OwnedProcess;

use super::{serialized, ProcessResources};

/// Linux process identity; start time is the raw `/proc/PID/stat` clock-tick value.
#[derive(
    Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, serde::Serialize, serde::Deserialize,
)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ProcessIdentity {
    pub process_id: u32,
    #[serde(
        serialize_with = "serialized::u64",
        deserialize_with = "serialized::deserialize_u64"
    )]
    pub start_time_ticks: u64,
}

/// A bounded observation of the retained child, never of the test runner.
/// Linux capture errors mean unavailable evidence, not observed zero resources.
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ChildProcessResources {
    pub identity: ProcessIdentity,
    pub process: ProcessResources,
    #[serde(
        serialize_with = "serialized::u64",
        deserialize_with = "serialized::deserialize_u64"
    )]
    pub task_count: u64,
    #[serde(
        serialize_with = "serialized::u64",
        deserialize_with = "serialized::deserialize_u64"
    )]
    pub unique_socket_count: u64,
    #[serde(
        serialize_with = "serialized::u64",
        deserialize_with = "serialized::deserialize_u64"
    )]
    pub listening_tcp_socket_count: u64,
    pub descendants: Vec<ProcessIdentity>,
    pub sample_attempts: u8,
}

/// Probe safety ceilings, independent of the measured node's configured capacity.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ProbeLimits {
    pub maximum_file_bytes: usize,
    pub maximum_tasks: usize,
    pub maximum_file_descriptors: usize,
    pub maximum_descendants: usize,
    pub maximum_descendant_depth: usize,
    pub maximum_network_table_bytes: usize,
    pub maximum_network_rows: usize,
    pub maximum_total_bytes: usize,
    pub maximum_attempts: u8,
}

impl Default for ProbeLimits {
    fn default() -> Self {
        Self {
            maximum_file_bytes: 64 * 1024,
            maximum_tasks: 256,
            maximum_file_descriptors: 4096,
            maximum_descendants: 32,
            maximum_descendant_depth: 4,
            maximum_network_table_bytes: 1024 * 1024,
            maximum_network_rows: 8192,
            maximum_total_bytes: 4 * 1024 * 1024,
            maximum_attempts: 3,
        }
    }
}

impl ProbeLimits {
    pub fn validate(self) -> io::Result<()> {
        if !(1..=64 * 1024).contains(&self.maximum_file_bytes)
            || !(1..=256).contains(&self.maximum_tasks)
            || !(1..=4096).contains(&self.maximum_file_descriptors)
            || self.maximum_descendants > 32
            || !(1..=4).contains(&self.maximum_descendant_depth)
            || !(1..=1024 * 1024).contains(&self.maximum_network_table_bytes)
            || !(1..=8192).contains(&self.maximum_network_rows)
            || !(1..=4 * 1024 * 1024).contains(&self.maximum_total_bytes)
            || !(1..=3).contains(&self.maximum_attempts)
        {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "invalid child resource probe limits",
            ));
        }
        Ok(())
    }
}

pub struct ChildProcessProbe {
    identity: ProcessIdentity,
    limits: ProbeLimits,
}

impl ChildProcessProbe {
    /// Binds a live, retained child to its kernel start-time identity.
    pub fn bind(child: &mut OwnedProcess, limits: ProbeLimits) -> io::Result<Self> {
        limits.validate()?;
        live(child)?;
        #[cfg(target_os = "linux")]
        {
            let identity = super::linux::identity(child.id(), limits)?;
            live(child)?;
            Ok(Self { identity, limits })
        }
        #[cfg(not(target_os = "linux"))]
        Err(io::Error::new(
            io::ErrorKind::Unsupported,
            "child resource probe requires Linux",
        ))
    }

    #[must_use]
    pub const fn identity(&self) -> ProcessIdentity {
        self.identity
    }

    /// Samples only this retained child's process tree and owned socket inodes.
    /// Retries transient descriptor/process churn at most the configured limit.
    pub fn capture(&self, child: &mut OwnedProcess) -> io::Result<ChildProcessResources> {
        live(child)?;
        if child.id() != self.identity.process_id {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "resource probe belongs to another child",
            ));
        }
        #[cfg(target_os = "linux")]
        {
            for attempt in 1..=self.limits.maximum_attempts {
                let result = super::linux::capture(self.identity, self.limits, attempt);
                live(child)?;
                match result {
                    Ok(observation) => return Ok(observation),
                    Err(error) if transient(&error) && attempt < self.limits.maximum_attempts => {}
                    Err(error) => return Err(error),
                }
            }
            Err(io::Error::other("child resource observation unavailable"))
        }
        #[cfg(not(target_os = "linux"))]
        {
            let _ = self.limits;
            Err(io::Error::new(
                io::ErrorKind::Unsupported,
                "child resource probe requires Linux",
            ))
        }
    }
}

fn live(child: &mut OwnedProcess) -> io::Result<()> {
    if child.try_status()?.is_some() {
        Err(io::Error::new(
            io::ErrorKind::NotFound,
            "child process is no longer live",
        ))
    } else {
        Ok(())
    }
}

#[cfg(target_os = "linux")]
fn transient(error: &io::Error) -> bool {
    matches!(
        error.kind(),
        io::ErrorKind::NotFound | io::ErrorKind::Interrupted
    )
}

#[cfg(test)]
mod tests;
