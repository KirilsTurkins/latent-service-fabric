//! Physical catalog destruction precedes the final retained policy observation.
use super::Catalogs;
use crate::config::NodeSettings;
use std::time::Instant;

#[cfg(all(test, target_os = "linux", target_arch = "x86_64"))]
mod tests;

#[cfg(all(test, target_os = "linux", target_arch = "x86_64"))]
pub(super) fn observe_inspection(
    catalogs: &Catalogs,
    response: &latent_core::native_capacity::NativeBufferPermit,
) {
    tests::inspectors::observe(catalogs, response);
}

impl Catalogs {
    pub(super) async fn retire_recovery(mut self, settings: &NodeSettings) -> bool {
        // Keep the evidence owner after the deployment/binding graph is gone.
        // Its original work cutoff must not become successful after late cleanup.
        let policies = self.policies.take();
        let deadline = Instant::now() + settings.shutdown_grace();
        let mut clean = true;
        if let Some(provider) = &self.providers {
            clean &= provider
                .shutdown(deadline)
                .await
                .is_ok_and(|report| report.clean);
        }
        if let Some(rollout) = &self.rollouts {
            clean &= rollout
                .shutdown(settings.shutdown_grace())
                .await
                .is_ok_and(crate::standalone::rollouts::RolloutShutdownReport::clean);
        }
        let policy_report = if let Some(policy) = &policies {
            let report = policy.shutdown(deadline).await;
            clean &= report.work_completed && report.active_jobs == 0;
            Some(report)
        } else {
            None
        };
        #[cfg(all(test, target_os = "linux", target_arch = "x86_64"))]
        tests::observe_policy_shutdown(policy_report).await;
        if let Some(telemetry) = self.telemetry.take() {
            clean &= telemetry.runtime.shutdown().await.is_ok();
        }
        if let Some(control) = self.control.take() {
            clean &= control.shutdown(settings.shutdown_grace()).await.is_ok();
        }
        let coordinator_joined = match &self.rollouts {
            Some(rollout) => rollout.worker_joined().await,
            None => true,
        };
        clean &= coordinator_joined;
        // A still-owned coordinator can submit audit work. Match node shutdown:
        // never join audit behind an unfinished blocking coordinator join.
        if let Some(audit) = self.audit.as_ref().filter(|_| coordinator_joined) {
            clean &= audit
                .shutdown(settings.shutdown_grace())
                .await
                .is_ok_and(crate::standalone::audit::AuditShutdownReport::clean);
        }
        drop(self);
        if let (Some(policy), Some(previous)) = (&policies, policy_report) {
            clean &= policy.snapshot(previous.work_completed).clean();
        }
        clean
    }
}
