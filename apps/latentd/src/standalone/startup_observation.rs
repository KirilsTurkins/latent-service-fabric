//! Private operator startup tracing. A scope retains only finite failures from
//! the ordinary startup future; it grants no authority and changes no owner.
use super::{
    state::StartupFailure as Failure, PlatformError, RuntimeThreads, ShutdownReport, StandaloneNode,
};
use crate::config::NodeSettings;
use latent_core::{PlatformErrorCode, PrincipalKind, TenantId};
use serde::Serialize;
use std::{cell::RefCell, future::Future};

const MAXIMUM_FAILURES: usize = 32;
tokio::task_local! {
    static FAILURES: RefCell<Trace>;
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
pub(super) enum Stage {
    Configuration,
    ExecutionProfile,
    AuditCatalog,
    SupplyChainCatalog,
    ArtifactCatalog,
    PolicyCatalog,
    DeploymentCatalog,
    RolloutCatalog,
    CatalogAuditReconciliation,
    ProviderCatalog,
    NodeComposition,
    NodeServices,
    StateConfiguration,
    StateClock,
    StateOperations,
    NativeCapacity,
    CommandWaiters,
    EffectAuthority,
    EffectInstallation,
    ProtectedStoreAdmission,
    ProtectedStoreStartup,
    EffectDispatcher,
    StateManagement,
    NodeStart,
    NodeShutdown,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
struct Observation {
    stage: Stage,
    failure: Failure,
}

#[derive(Default)]
struct Trace {
    observations: [Option<Observation>; MAXIMUM_FAILURES],
    retained: usize,
    truncated: bool,
}

/// The private helper's observation of an actual normal startup attempt.
/// Success includes its actual ordinary shutdown report. Failure carries only
/// producer-owned finite codes, never configuration, paths or error messages.
#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct StartupFailureReport {
    schema_version: &'static str,
    startup_succeeded: bool,
    terminal_failure: Option<Failure>,
    observations: Vec<Observation>,
    truncated: bool,
    shutdown: Option<ShutdownReport>,
}

pub(super) fn record(stage: Stage, failure: impl Into<Failure>) {
    let _ = FAILURES.try_with(|slot| {
        if let Ok(mut trace) = slot.try_borrow_mut() {
            if trace.retained == MAXIMUM_FAILURES {
                trace.truncated = true;
            } else {
                let index = trace.retained;
                trace.observations[index] = Some(Observation {
                    stage,
                    failure: failure.into(),
                });
                trace.retained += 1;
            }
        }
    });
}

pub(super) fn record_platform(stage: Stage, error: &PlatformError) {
    record(stage, Failure::from(error));
}

pub(super) fn platform<T>(
    stage: Stage,
    result: Result<T, PlatformError>,
) -> Result<T, PlatformError> {
    result.inspect_err(|error| record_platform(stage, error))
}

async fn capture<T>(future: impl Future<Output = T>) -> (T, Trace) {
    FAILURES
        .scope(RefCell::new(Trace::default()), async {
            let output = future.await;
            let trace = FAILURES.with(|slot| std::mem::take(&mut *slot.borrow_mut()));
            (output, trace)
        })
        .await
}

impl StandaloneNode {
    /// Private native operator fixture: runs the actual normal startup and,
    /// on success, actual shutdown. Startup may durably advance the node epoch;
    /// this is not the read-only transaction-store diagnosis. Only a protected
    /// configured transport administrator for the actual tenant may request it.
    pub async fn diagnose_startup(
        settings: NodeSettings,
        credential: &str,
        tenant: &TenantId,
        control_runtime: tokio::runtime::Handle,
        threads: RuntimeThreads,
    ) -> Result<StartupFailureReport, PlatformError> {
        let principal = super::transport::credential_principal(&settings.transport, credential)
            .ok_or_else(denied)?;
        if !settings.credentials_from_protected_file
            || principal.kind != PrincipalKind::Administrator
            || principal.tenant.as_ref() != Some(tenant)
            || settings.state.is_none()
        {
            return Err(denied());
        }
        let startup = async {
            match platform(
                Stage::NodeStart,
                Box::pin(Self::start(settings, control_runtime, threads)).await,
            ) {
                Err(error) => (false, Some(Failure::from(&error)), None),
                Ok(node) => match platform(Stage::NodeShutdown, Box::pin(node.shutdown()).await) {
                    Ok(shutdown) => (true, None, Some(shutdown)),
                    Err(error) => (true, Some(Failure::from(&error)), None),
                },
            }
        };
        let startup = std::pin::pin!(startup);
        let (outcome, trace) = capture(startup).await;
        Ok(StartupFailureReport {
            schema_version: "latent.startup-failure-observation.v1",
            startup_succeeded: outcome.0,
            terminal_failure: outcome.1,
            observations: trace.observations.into_iter().flatten().collect(),
            truncated: trace.truncated,
            shutdown: outcome.2,
        })
    }
}

fn denied() -> PlatformError {
    super::error(
        PlatformErrorCode::PermissionDenied,
        "native-startup-diagnosis-refused",
    )
}

#[cfg(test)]
mod tests;
