use crate::config::CapabilityPolicyConfig;
use latent_artifacts::LifecycleAuthorityHandle;
use latent_core::{PlatformError, PlatformErrorCode};
use latent_policy::capability::{PolicyControlHandle, PolicyStore};
use serde::Serialize;
use std::{path::Path, sync::Arc, time::Instant};

pub(super) struct PolicyRuntime {
    handle: PolicyControlHandle,
}
#[derive(Debug, Clone, Copy, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PolicyShutdownReport {
    pub work_completed: bool,
    pub active_jobs: usize,
    pub retained_read_owners: usize,
}
impl PolicyShutdownReport {
    pub(super) fn clean(self) -> bool {
        self.work_completed && self.active_jobs == 0 && self.retained_read_owners == 0
    }
}
impl PolicyRuntime {
    pub(super) fn open(
        root: &Path,
        config: Option<CapabilityPolicyConfig>,
        catalog: LifecycleAuthorityHandle,
        runtime: Option<&tokio::runtime::Handle>,
    ) -> Result<Option<Self>, PlatformError> {
        let Some(config) = config else {
            // Presence, including a damaged path/marker, cannot silently disable
            // an existing policy owner on restart. Privileged whole-root rollback
            // remains outside this local protection, as with admission history.
            match std::fs::symlink_metadata(root) {
                Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(None),
                _ => {
                    return Err(super::error(
                        PlatformErrorCode::PermissionDenied,
                        "capability-policy-owner-required",
                    ))
                }
            }
        };
        let runtime = runtime.ok_or_else(|| {
            super::error(
                PlatformErrorCode::InvalidArgument,
                "capability-policy-control-runtime-required",
            )
        })?;
        let store = Arc::new(PolicyStore::open(root, config.store, catalog)?);
        Ok(Some(Self {
            handle: PolicyControlHandle::new(store, runtime.clone(), config.maximum_control_jobs)?,
        }))
    }
    pub(super) fn handle(&self) -> PolicyControlHandle {
        self.handle.clone()
    }
    pub(super) async fn shutdown(&self, deadline: Instant) -> PolicyShutdownReport {
        let completed = self.handle.shutdown(deadline).await;
        PolicyShutdownReport {
            work_completed: completed,
            active_jobs: self.handle.active_jobs(),
            retained_read_owners: self.handle.store().retained_read_owners(),
        }
    }
}
impl Drop for PolicyRuntime {
    fn drop(&mut self) {
        self.handle.retire();
    }
}
