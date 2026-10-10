//! Sealed actual current deployment/namespace selection for native installation.
mod pin;
use pin::SelectionPin;

use super::{error, DirectoryDeploymentRepository};
use latent_artifacts::{ReleaseUseEligibility, SelectedTransactionAsset};
use latent_core::{
    native_capacity::{
        NativeAdmissionClass, NativeBufferClass, NativeBufferPermit, NativeCapacityOwner,
        NativeReservation,
    },
    PlatformError, PlatformErrorCode,
};
use latent_manifest::TransactionOperationMode;
use latent_routing::InvocationTarget;
use latent_state::namespace::catalog::{NamespaceCatalog, NamespaceRead};
use std::sync::Arc;

/// No current catalog or whole retired snapshot is kept alive by this capture.
/// Its exact caller job charge follows the bounded copied metadata/real handle.
pub struct CapturedTransactionSelection {
    pin: Arc<SelectionPin>,
    original: Arc<NativeReservation>,
    _memory: NativeBufferPermit,
}

/// Resident metadata transferred only while the actual ORIGINAL capture is
/// current. The separately prepaid resident charge grants no new authority.
pub struct InstalledTransactionSelection {
    pin: Arc<SelectionPin>,
    resident: Arc<NativeReservation>,
    _memory: NativeBufferPermit,
}

impl CapturedTransactionSelection {
    pub const METADATA_BYTES: u64 = 64 * 1024;

    /// The same actual bounded metadata leaf used by the signed producer. This
    /// private port is not a package admission or public installation API.
    #[allow(
        clippy::too_many_arguments,
        reason = "Original source owners and bounded selector metadata are independent"
    )]
    fn capture_metadata(
        store: &DirectoryDeploymentRepository,
        target: &InvocationTarget,
        routing_key: Option<&str>,
        entity: Option<&str>,
        namespace: NamespaceRead,
        namespaces: &NamespaceCatalog,
        publication: &ReleaseUseEligibility,
        write: bool,
        native: &NativeCapacityOwner,
        original: Arc<NativeReservation>,
    ) -> Result<Self, PlatformError> {
        if !original.is_from_owner(native)
            || original.class() != NativeAdmissionClass::Recovery
            || !namespaces.uses_native_capacity(native)
            || store.admission.is_none()
        {
            return Err(denied());
        }
        let memory = original
            .reserve_buffer(NativeBufferClass::Work, Self::METADATA_BYTES)
            .map_err(|_| capacity())?;
        let pin = SelectionPin::capture(
            store,
            target,
            routing_key,
            entity,
            namespace,
            namespaces,
            publication,
            write,
        )?;
        let captured = Self {
            pin: Arc::new(pin),
            original,
            _memory: memory,
        };
        captured.with_current(&mut || Ok(()))?;
        Ok(captured)
    }

    /// Short final installation metadata fence, ending in the same original
    /// caller's Native fence. Do not nest another same-Native check in `action`.
    pub fn with_current(
        &self,
        action: &mut dyn FnMut() -> Result<(), PlatformError>,
    ) -> Result<(), PlatformError> {
        self.pin.with_current(&self.pin.publication, &mut || {
            self.original
                .with_live(&mut *action)
                .map_err(|_| unavailable())?
        })
    }

    /// Move physical pins to the existing SAME-node resident Recovery owner;
    /// reserve before moving, and recheck the original capture rather than
    /// retargeting a current catalog or renewing its finite caller deadline.
    pub fn into_resident(
        self,
        native: &NativeCapacityOwner,
        resident: Arc<NativeReservation>,
    ) -> Result<InstalledTransactionSelection, PlatformError> {
        if !self.original.is_from_owner(native)
            || !resident.is_from_owner(native)
            || resident.class() != NativeAdmissionClass::Recovery
            || Arc::ptr_eq(&self.original, &resident)
        {
            return Err(denied());
        }
        let mut memory = Some(
            resident
                .reserve_buffer(NativeBufferClass::Work, Self::METADATA_BYTES)
                .map_err(|_| capacity())?,
        );
        let mut resident = Some(resident);
        let mut installed = None;
        self.with_current(&mut || {
            installed = Some(InstalledTransactionSelection {
                pin: Arc::clone(&self.pin),
                resident: resident.take().ok_or_else(denied)?,
                _memory: memory.take().ok_or_else(denied)?,
            });
            Ok(())
        })?;
        installed.ok_or_else(denied)
    }
}

impl DirectoryDeploymentRepository {
    /// Caller supplies the opaque exact signed companion from this SAME actual
    /// original job and a namespace read from the configured protected worker.
    /// DTO routing/entity selectors confer no permission; the catalog's weighted
    /// selection, current grant and actual lifecycle handle seal their identity.
    #[allow(
        clippy::too_many_arguments,
        reason = "Original signed, native, namespace and routing owners are independent"
    )]
    pub fn capture_transaction_selection(
        &self,
        asset: &SelectedTransactionAsset,
        target: &InvocationTarget,
        routing_key: Option<&str>,
        entity: Option<&str>,
        namespace: NamespaceRead,
        namespaces: &NamespaceCatalog,
        native: &NativeCapacityOwner,
        original: Arc<NativeReservation>,
    ) -> Result<CapturedTransactionSelection, PlatformError> {
        if !asset.is_from_reservation(&original)
            || !original.is_from_owner(native)
            || original.class() != NativeAdmissionClass::Recovery
            || !namespaces.uses_native_capacity(native)
            || self.admission.is_none()
        {
            return Err(denied());
        }
        let operation = asset
            .declaration()
            .operations
            .iter()
            .find(|operation| operation.operation == target.function.0)
            .ok_or_else(denied)?;
        if namespace.record().id.0 != asset.declaration().namespace
            || namespace.record().state_schema != asset.declaration().state_schema
            || namespace.record().tenant != target.tenant
            || Some(&target.tenant) != asset.publication().tenant()
            || target.service.0 != asset.metadata().manifest().metadata.name
        {
            return Err(denied());
        }
        let captured = CapturedTransactionSelection::capture_metadata(
            self,
            target,
            routing_key,
            entity,
            namespace,
            namespaces,
            asset.publication(),
            operation.mode == TransactionOperationMode::StrictCommand,
            native,
            original,
        )?;
        if captured.pin.deployment.0 != asset.declaration().deployment {
            return Err(denied());
        }
        Ok(captured)
    }
}

fn denied() -> PlatformError {
    error(
        PlatformErrorCode::PermissionDenied,
        "transaction-selection-owner",
    )
}
fn capacity() -> PlatformError {
    error(
        PlatformErrorCode::ResourceExhausted,
        "transaction-selection-metadata",
    )
}
fn unavailable() -> PlatformError {
    error(
        PlatformErrorCode::Unavailable,
        "transaction-selection-current",
    )
}
