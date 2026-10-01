//! Existing shared maintenance guard around the original physical compactor.
use super::{MaintenanceClock, MaintenanceProgress, ResultMaintenanceOwner};
use crate::atomic::{writer::fenced_error, AtomicError};
use latent_core::{StateNamespaceId, TenantId};
use latent_state::{
    embedded::{CompactionLimits, CompactionReport, EmbeddedStore, ExpectedRow},
    namespace::{NamespaceRecord, NamespaceVersion},
};

/// Host-selected scope and original business version. Actual history/recovery
/// rows are captured from the same engine and fenced; the values grant nothing.
#[derive(Clone, Debug)]
pub struct MaintenanceCompactionScope {
    pub tenant: TenantId,
    pub namespace: StateNamespaceId,
    pub expected: NamespaceVersion,
}

impl ResultMaintenanceOwner {
    /// Execute on the original reserved `RecoveryWrite` worker. The host must
    /// reserve `limits.maximum_scratch_bytes` and its bounded request/response
    /// overhead before queueing, and hold that permit through physical return.
    /// Current checkpoint/maintenance permission is checked again after native
    /// view/writer drain and exact namespace/history/clock row validation.
    /// Compaction preserves all logical records, protective floors and tokens.
    ///
    /// # Errors
    /// Refuses another maintenance step, a stale version, missing/unapproved
    /// clock anchor, paused history/restore, live readers/writers, revoked host
    /// acceptance or insufficient native/scratch bounds. Physical uncertainty
    /// requires recovery and never publishes a clean completion.
    pub fn compact(
        &self,
        store: &EmbeddedStore,
        scope: &MaintenanceCompactionScope,
        limits: CompactionLimits,
        clock: MaintenanceClock,
        mut authorize: impl FnMut(&NamespaceRecord) -> Result<(), AtomicError>,
    ) -> Result<CompactionReport, AtomicError> {
        let _physical_step = self.enter()?;
        clock.validate()?;
        let view = store.snapshot()?;
        let mut checks = latent_state::recovery::maintenance::namespace_expectations(
            &view,
            &scope.tenant,
            &scope.namespace,
            scope.expected.incarnation,
        )?
        .to_vec();
        let namespace =
            NamespaceRecord::decode(checks[1].value.as_deref().ok_or(AtomicError::Corrupt)?)
                .map_err(|_| AtomicError::Corrupt)?;
        if namespace.version != scope.expected {
            return Err(AtomicError::Conflict);
        }
        authorize(&namespace)?;
        let original = view
            .get(&MaintenanceProgress::key())?
            .ok_or(AtomicError::RecoveryRequired)?;
        clock.next(&MaintenanceProgress::decode(&original)?)?;
        checks.push(ExpectedRow {
            key: MaintenanceProgress::key(),
            value: Some(original),
        });
        drop(view);
        store
            .compact_fenced(limits, &checks, || authorize(&namespace))
            .map_err(fenced_error)
    }
}
