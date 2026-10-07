//! Serialized control by the owning development node; no guest-facing gateway.
use super::{unavailable, ProviderRuntime};
use crate::config::StreamReloadGuard;
use latent_core::{PlatformError, PlatformErrorCode};
use serde::Serialize;
use std::time::{Duration, Instant};

#[cfg(test)]
#[path = "stream_control_tests.rs"]
mod tests;

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct StreamControlStatus {
    pub operation: &'static str,
    pub outcome: &'static str,
    pub execution_permission: bool,
    pub provider: super::ProviderDescriptor,
    pub configured_generation: u64,
    pub installed_binding_generation: u64,
    pub binding_publication_pending: bool,
    pub unavailable_binding_plans: usize,
    pub stream: latent_streams::StreamStatus,
    pub failure_code: Option<String>,
}

fn conflict() -> PlatformError {
    PlatformError {
        code: PlatformErrorCode::StateConflict,
        message: "stream-control-current-generation-mismatch".into(),
        retryable: false,
        details: vec![],
    }
}

impl ProviderRuntime {
    fn stream_index(&self) -> Result<usize, PlatformError> {
        let mut indices = self
            .descriptors
            .iter()
            .enumerate()
            .filter(|(_, row)| {
                row.capability == latent_capabilities::broker::network::STREAM_CAPABILITY
            })
            .map(|(index, _)| index);
        let index = indices.next().ok_or_else(unavailable)?;
        if indices.next().is_some() {
            return Err(unavailable());
        }
        Ok(index)
    }

    pub fn check_stream_reload_owner(
        &self,
        guard: &StreamReloadGuard,
    ) -> Result<(), PlatformError> {
        if !guard.belongs_to(self.stream_reload_binding) {
            return Err(conflict());
        }
        Ok(())
    }

    pub fn stream_control_status(
        &self,
        operation: &'static str,
        outcome: &'static str,
        failure: Option<PlatformErrorCode>,
    ) -> Result<StreamControlStatus, PlatformError> {
        let stream = self
            .streams
            .as_ref()
            .ok_or_else(unavailable)?
            .status()
            .map_err(|_| unavailable())?;
        let reference = self
            .stream_binding_reference
            .as_ref()
            .ok_or_else(unavailable)?;
        let (_, _, _, unavailable_plans) = self
            .stream_catalog
            .as_ref()
            .ok_or_else(unavailable)?
            .binding_inventory();
        Ok(StreamControlStatus {
            operation,
            outcome,
            execution_permission: false,
            provider: self.descriptors[self.stream_index()?].clone(),
            configured_generation: stream.configuration_epoch,
            installed_binding_generation: reference.configuration_epoch(),
            binding_publication_pending: reference.configuration_epoch()
                != stream.configuration_epoch
                || reference.configuration_digest() != stream.configuration_digest,
            unavailable_binding_plans: unavailable_plans,
            stream,
            failure_code: failure.map(|code| format!("{code:?}")),
        })
    }

    /// The config file's epoch must strictly increase. A repeated signal cannot
    /// repeat rotation, restore old authority, or erase retained physical owners.
    pub async fn reload_streams(
        &mut self,
        guard: &StreamReloadGuard,
    ) -> Result<StreamControlStatus, PlatformError> {
        self.check_stream_reload_owner(guard)?;
        let _input_metadata = self.pools.reserve_protocol_metadata(1024 * 1024)?;
        let candidate = guard.replacement()?;
        let index = self.stream_index()?;
        let installed = &self.descriptors[index];
        if candidate.identity.id != installed.id
            || candidate.identity.tenant != installed.tenant
            || candidate.identity.service != installed.service
        {
            return Err(conflict());
        }
        let owner = self.streams.as_ref().ok_or_else(unavailable)?;
        let current = owner.reference().map_err(|_| unavailable())?;
        if candidate.identity.epoch <= current.configuration_epoch() {
            return Err(conflict());
        }
        let replacement = owner
            .rotate(
                current.configuration_epoch(),
                candidate.identity.epoch,
                candidate.configuration,
            )
            .map_err(|_| unavailable())?;
        // Report the actual installed generation immediately, even when the
        // subsequent immutable catalog publication fails or remains unavailable.
        self.descriptors[index].configuration_digest = replacement.configuration_digest().into();
        self.descriptors[index].configuration_epoch = replacement.configuration_epoch().to_string();
        self.publish_stream_bindings("reload").await
    }

    /// Explicitly publish/refresh the installed reference. This operation has no
    /// provider rotation or network effect, and is never called in a retry loop.
    pub async fn publish_stream_bindings(
        &mut self,
        operation: &'static str,
    ) -> Result<StreamControlStatus, PlatformError> {
        let expected = self
            .stream_binding_reference
            .as_ref()
            .ok_or_else(unavailable)?
            .clone();
        let replacement = self
            .streams
            .as_ref()
            .ok_or_else(unavailable)?
            .reference()
            .map_err(|_| unavailable())?;
        let catalog = self
            .stream_catalog
            .as_ref()
            .ok_or_else(unavailable)?
            .clone();
        let deadline = Instant::now() + Duration::from_secs(30);
        let work =
            catalog.prepare_provider_reference_update(&expected, replacement.clone(), |bytes| {
                self.pools.reserve_protocol_metadata(bytes)
            });
        let prepared = match tokio::time::timeout_at(deadline.into(), work).await {
            Ok(Ok(prepared)) => prepared,
            Ok(Err(error)) => {
                return self.stream_control_status(
                    operation,
                    "installed-generation-binding-publication-unconfirmed",
                    Some(error.code),
                )
            }
            Err(_) => {
                return self.stream_control_status(
                    operation,
                    "installed-generation-binding-publication-unconfirmed",
                    Some(PlatformErrorCode::DeadlineExceeded),
                )
            }
        };
        if let Err(error) = catalog.commit_provider_reference_update(prepared) {
            return self.stream_control_status(
                operation,
                "installed-generation-binding-publication-unconfirmed",
                Some(error.code),
            );
        }
        self.stream_binding_reference = Some(replacement);
        self.stream_control_status(operation, "installed-generation-bindings-published", None)
    }

    pub async fn drain_streams(&mut self) -> Result<StreamControlStatus, PlatformError> {
        let owner = self.streams.as_ref().ok_or_else(unavailable)?;
        let status = owner
            .drain(Instant::now() + Duration::from_secs(30))
            .await
            .map_err(|_| unavailable())?;
        let outcome = if status.usage.owners == 0 {
            "drained"
        } else {
            "retained-owners-not-refunded"
        };
        self.stream_control_status("drain", outcome, None)
    }
}
