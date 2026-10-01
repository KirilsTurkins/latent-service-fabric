use super::{Catalogs, NodeSettings, StandaloneNode};
use crate::standalone::state::NativeTransactionHostInspection;
use latent_core::{PlatformError, PlatformErrorCode};
use std::time::Instant;

impl StandaloneNode {
    /// Inspect checked transaction profiles with the real native provider owners
    /// before granting staging/dispatch authority. No listener, guest activation,
    /// state store or effect dispatcher is started. Configuration/catalog owners
    /// follow ordinary protected startup and complete their ordinary shutdown.
    pub async fn inspect_transaction_hosts(
        settings: &NodeSettings,
        runtime: &tokio::runtime::Handle,
    ) -> Result<NativeTransactionHostInspection, PlatformError> {
        let catalogs = Catalogs::open_with_control(settings, runtime).await?;
        let result = catalogs.inspect_transaction_hosts(settings).await;
        let shutdown = catalogs.close_inspection(settings).await;
        result.and_then(|observation| shutdown.map(|()| observation))
    }
}

impl Catalogs {
    async fn inspect_transaction_hosts(
        &self,
        settings: &NodeSettings,
    ) -> Result<NativeTransactionHostInspection, PlatformError> {
        crate::standalone::state::inspect_host_configuration(
            settings,
            &self.artifacts,
            self.providers.as_deref(),
            self.policies
                .as_ref()
                .ok_or_else(super::mode_error)?
                .handle()
                .store(),
            self.clock.clone(),
        )
        .await
    }

    async fn close_inspection(mut self, settings: &NodeSettings) -> Result<(), PlatformError> {
        let deadline = Instant::now() + settings.shutdown_grace;
        let mut failure = None;
        self.capabilities.take();
        if let Some(providers) = self.providers.take() {
            match providers.shutdown(deadline).await {
                Ok(report) if report.clean => (),
                Ok(_) => {
                    failure.get_or_insert_with(unclean);
                }
                Err(error) => {
                    failure.get_or_insert(error);
                }
            }
        }
        if let Some(policies) = self.policies.take() {
            if !policies.shutdown(deadline).await.clean() {
                failure.get_or_insert_with(unclean);
            }
        }
        if let Some(rollouts) = &self.rollouts {
            match rollouts
                .shutdown(deadline.saturating_duration_since(Instant::now()))
                .await
            {
                Ok(report) if report.clean() => (),
                Ok(_) => {
                    failure.get_or_insert_with(unclean);
                }
                Err(error) => {
                    failure.get_or_insert(error);
                }
            }
        }
        if let Some(telemetry) = self.telemetry.take() {
            if let Err(error) = telemetry.runtime.shutdown().await {
                failure.get_or_insert(error);
            }
        }
        if let Some(control) = self.control.take() {
            if let Err(error) = control
                .shutdown(deadline.saturating_duration_since(Instant::now()))
                .await
            {
                failure.get_or_insert(error);
            }
        }
        let joined = match &self.rollouts {
            Some(owner) => owner.worker_joined().await,
            None => true,
        };
        if joined {
            if let Some(audit) = &self.audit {
                match audit
                    .shutdown(deadline.saturating_duration_since(Instant::now()))
                    .await
                {
                    Ok(report) if report.clean() => (),
                    Ok(_) => {
                        failure.get_or_insert_with(unclean);
                    }
                    Err(error) => {
                        failure.get_or_insert(error);
                    }
                }
            }
        } else {
            failure.get_or_insert_with(unclean);
        }
        failure.map_or(Ok(()), Err)
    }
}

fn unclean() -> PlatformError {
    super::error(
        PlatformErrorCode::DeadlineExceeded,
        "transaction-host-inspection-shutdown-incomplete",
    )
}
