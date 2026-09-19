use serde::Serialize;

#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
mod runtime;
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
pub(super) use runtime::ProviderRuntime;
#[cfg(not(all(target_os = "linux", target_arch = "x86_64")))]
mod unsupported;
#[cfg(not(all(target_os = "linux", target_arch = "x86_64")))]
pub(super) use unsupported::ProviderRuntime;

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ProviderDescriptor {
    id: String,
    tenant: String,
    service: String,
    capability: String,
    profile: String,
    configuration_digest: String,
    configuration_epoch: String,
}

#[derive(Debug, Clone, Copy, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ProviderShutdownReport {
    pub clean: bool,
    pub control_owners: usize,
    pub connections: usize,
    pub pending_requests: usize,
    pub running_requests: usize,
    pub workers: usize,
    pub cleanup_jobs: usize,
    pub failed_cleanup: usize,
    pub sessions: usize,
    pub handles: usize,
    pub calls: usize,
    pub results: usize,
    pub io_calls: usize,
    pub io_retained_bytes: usize,
    pub blob_stages: usize,
    pub blob_handles: usize,
    pub blob_work: usize,
}
