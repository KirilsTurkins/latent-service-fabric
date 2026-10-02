//! Bounded native decoder closure over actual retained signed package sources.
use super::super::{effects::RecoveryProfile, InstalledTransactionOperation};
use super::{
    assets::{self, SchemaEvidence},
    profile::Profile,
};
use latent_artifacts::DirectoryArtifactRepository;
use latent_commit::atomic::{CommandRecord, Outcome, SourceIdentity};
use latent_core::PlatformError;
use latent_effects::dispatch::EffectRecord;
use latent_state::{
    embedded::{Family, ReadView, RowKey, StoreError},
    namespace::compatibility::{RetainedCount, RetainedFormat, RetainedInventory, RetainedKind},
    recovery::snapshot::{RequiredArtifact, SnapshotClosure},
};
use std::sync::Arc;

pub(super) const LINKED: &str = "lsf.java718.native-linked-row-registry.v1";
pub(super) const VALUES: &str = "lsf-wit-values-v1";
pub(super) struct Catalog {
    pub selected: usize,
    pub schemas: Vec<SchemaEvidence>,
    pub effects: Vec<RecoveryProfile>,
    pub artifacts: Vec<RequiredArtifact>,
    pub formats: Vec<RetainedFormat>,
}
impl Catalog {
    pub async fn capture(
        repository: &Arc<DirectoryArtifactRepository>,
        installed: &[Arc<InstalledTransactionOperation>],
        effects: Vec<RecoveryProfile>,
        publication: &str,
    ) -> Result<Self, PlatformError> {
        if installed.len() > 128 || effects.len() > 128 {
            return Err(super::super::capacity());
        }
        let original = installed
            .iter()
            .find(|operation| operation.publication().publication().as_str() == publication)
            .ok_or_else(super::super::denied)?;
        Profile::installed(&original.publication().release().0)?;
        let mut schemas: Vec<SchemaEvidence> = Vec::new();
        for operation in installed {
            if operation.target().tenant != original.target().tenant
                || operation.namespace() != original.namespace()
                || operation.incarnation() != original.incarnation()
                || Profile::installed(&operation.publication().release().0).is_err()
                || schemas.iter().any(|prior| {
                    prior.operation.publication().publication()
                        == operation.publication().publication()
                })
            {
                continue;
            }
            if schemas.len() == latent_state::namespace::compatibility::REVISIONS_PER_COMPOSITION {
                return Err(super::super::capacity());
            }
            schemas.push(assets::capture(repository, Arc::clone(operation)).await?);
        }
        let selected = schemas
            .iter()
            .position(|schema| schema.operation.publication().publication().as_str() == publication)
            .ok_or_else(super::super::denied)?;
        let mut catalog = Self {
            selected,
            schemas,
            effects,
            artifacts: Vec::new(),
            formats: formats(),
        };
        for evidence in &catalog.schemas {
            for artifact in &evidence.artifacts {
                if let Some(prior) = catalog
                    .artifacts
                    .iter()
                    .find(|prior| prior.identity == artifact.identity)
                {
                    if prior != artifact {
                        return Err(super::super::denied());
                    }
                } else {
                    if catalog.artifacts.len()
                        == latent_state::recovery::snapshot::SNAPSHOT_ARTIFACTS
                    {
                        return Err(super::super::capacity());
                    }
                    catalog.artifacts.push(artifact.clone());
                }
            }
        }
        for effect in &catalog.effects {
            for (kind, identity) in [
                (RetainedKind::EffectPayload, &effect.profile.payload_format),
                (RetainedKind::AdapterProfile, &effect.profile.adapter),
                (RetainedKind::AdapterProfile, &effect.profile.destination),
                (
                    RetainedKind::AdapterProfile,
                    &effect.profile.idempotency_profile,
                ),
            ] {
                let format = RetainedFormat {
                    kind,
                    identity: identity.clone(),
                };
                if !catalog.formats.contains(&format) {
                    catalog.formats.push(format);
                }
            }
        }
        RetainedInventory::default()
            .require_decoders(&catalog.formats)
            .map_err(|_| super::super::denied())?;
        catalog
            .artifacts
            .sort_by(|one, two| one.identity.cmp(&two.identity));
        catalog.formats.sort();
        Ok(catalog)
    }
    pub fn primary(&self) -> &SchemaEvidence {
        &self.schemas[self.selected]
    }
    pub fn current(&self) -> Result<(), StoreError> {
        for evidence in &self.schemas {
            evidence
                .operation
                .publication()
                .check_current()
                .map_err(|_| StoreError::Unavailable)?;
        }
        Ok(())
    }
    pub fn closure(
        &self,
        view: &ReadView,
        deadline: std::time::Instant,
    ) -> Result<SnapshotClosure, StoreError> {
        self.current()?;
        super::super::validate_view(view)?;
        let mut inventory = RetainedInventory::default();
        latent_state::recovery::snapshot::visit_view(view, deadline, |_, key, bytes| {
            self.observe(view, key, bytes, &mut inventory)
        })?;
        inventory
            .require_decoders(&self.formats)
            .map_err(|_| StoreError::UnsupportedFormat)?;
        Ok(SnapshotClosure {
            inventory,
            required_artifacts: self.artifacts.clone(),
        })
    }
    fn observe(
        &self,
        view: &ReadView,
        key: &RowKey,
        bytes: &[u8],
        inventory: &mut RetainedInventory,
    ) -> Result<(), StoreError> {
        let count = RetainedCount {
            rows: 1,
            bytes: (key.key.len() + bytes.len() + 1) as u64,
            unresolved: 0,
        };
        match key.family {
            Family::Command | Family::Attempt if bytes.starts_with(b"LCM\0") => {
                self.command(bytes, inventory, count)
            }
            Family::Outbox => self.effect(bytes, inventory, count),
            Family::PayloadReference => {
                let payload = latent_effects::payload::PayloadRecord::decode(bytes)
                    .map_err(|_| StoreError::Corrupt)?;
                let effect_key = latent_effects::dispatch_store::effect_row_key(payload.effect())?;
                let effect =
                    EffectRecord::decode(&view.get(&effect_key)?.ok_or(StoreError::Corrupt)?)
                        .map_err(|_| StoreError::Corrupt)?;
                let authority = effect.authority().map_err(|_| StoreError::Corrupt)?;
                observe(
                    inventory,
                    RetainedKind::EffectPayload,
                    &authority.profile().payload_format,
                    count,
                )
            }
            Family::State | Family::Tombstone => {
                self.cell(view, key, bytes)?;
                observe(inventory, RetainedKind::MigrationCheckpoint, LINKED, count)
            }
            Family::Result => {
                let unresolved = u64::from(bytes.starts_with(b"LCP\0"));
                for kind in [RetainedKind::SuccessResult, RetainedKind::RejectionResult] {
                    observe(
                        inventory,
                        kind,
                        VALUES,
                        RetainedCount {
                            unresolved,
                            ..count
                        },
                    )?;
                }
                Ok(())
            }
            Family::Inbox => observe(inventory, RetainedKind::InboxIdentity, LINKED, count),
            Family::Attempt => observe(
                inventory,
                RetainedKind::CommandAttempt,
                LINKED,
                RetainedCount {
                    unresolved: u64::from(bytes.starts_with(b"LHP\0")),
                    ..count
                },
            ),
            Family::Maintenance
                if key
                    .key
                    .starts_with(latent_effects::dispatch_store::DUE_PREFIX) =>
            {
                observe(inventory, RetainedKind::OrderingGroup, LINKED, count)
            }
            _ => observe(inventory, RetainedKind::MigrationCheckpoint, LINKED, count),
        }
    }
    fn command(
        &self,
        bytes: &[u8],
        inventory: &mut RetainedInventory,
        count: RetainedCount,
    ) -> Result<(), StoreError> {
        let record = CommandRecord::decode(bytes).map_err(|_| StoreError::Corrupt)?;
        self.require_source(record.source())?;
        if record.key().tenant != self.primary().operation.target().tenant.0
            || record.key().namespace != self.primary().operation.namespace()
            || record.key().incarnation != self.primary().operation.incarnation().to_string()
        {
            return Err(StoreError::UnsupportedFormat);
        }
        let format = if bytes.starts_with(b"LCM\0\x04") {
            "lsf.command-record.v4"
        } else {
            "lsf.command-record.v3"
        };
        observe(
            inventory,
            RetainedKind::CommandAttempt,
            format,
            RetainedCount {
                unresolved: u64::from(record.outcome() == Outcome::Pending),
                ..count
            },
        )?;
        observe(inventory, RetainedKind::CommandFingerprint, VALUES, count)
    }
    fn effect(
        &self,
        bytes: &[u8],
        inventory: &mut RetainedInventory,
        count: RetainedCount,
    ) -> Result<(), StoreError> {
        let effect = EffectRecord::decode(bytes).map_err(|_| StoreError::Corrupt)?;
        let authority = effect.authority().map_err(|_| StoreError::Corrupt)?;
        let profile = self
            .effects
            .iter()
            .find(|entry| {
                &entry.scope == authority.scope() && &entry.profile == authority.profile()
            })
            .ok_or(StoreError::UnsupportedFormat)?;
        observe(
            inventory,
            RetainedKind::EffectEnvelope,
            "lsf.effect-record.v1",
            RetainedCount {
                unresolved: u64::from(!effect.disposition().terminal()),
                ..count
            },
        )?;
        for identity in [
            &profile.profile.adapter,
            &profile.profile.destination,
            &profile.profile.idempotency_profile,
        ] {
            observe(inventory, RetainedKind::AdapterProfile, identity, count)?;
        }
        Ok(())
    }
    fn cell(&self, view: &ReadView, key: &RowKey, bytes: &[u8]) -> Result<(), StoreError> {
        let observed = latent_state::session::inspect_cell(view, key, bytes)?;
        if observed.scope.tenant != self.primary().operation.target().tenant
            || observed.scope.namespace.0 != self.primary().operation.namespace()
            || observed.scope.incarnation != self.primary().operation.incarnation()
        {
            return Err(StoreError::UnsupportedFormat);
        }
        if let Some(value) = observed.value {
            if observed.key != b"aggregate/count"
                || !value.metadata.is_empty()
                || !self.schemas.iter().any(|schema| {
                    schema
                        .profile
                        .decode(&value.media_type, &value.bytes)
                        .is_some()
                })
            {
                return Err(StoreError::UnsupportedFormat);
            }
        }
        Ok(())
    }
    fn require_source(&self, source: &SourceIdentity) -> Result<(), StoreError> {
        if source.input_format != VALUES
            || source.result_format != VALUES
            || !self.schemas.iter().any(|evidence| {
                let operation = &evidence.operation;
                operation.publication().publication().as_str() == source.publication
                    && operation.publication().release().0 == source.release_digest
                    && operation.publication().release().0 == source.component_digest
                    && operation.contract_digest == source.contract_digest
                    && evidence
                        .schema
                        .declaration()
                        .readers
                        .iter()
                        .any(|schema| schema.as_str() == source.state_schema)
            })
        {
            return Err(StoreError::UnsupportedFormat);
        }
        Ok(())
    }
}
fn observe(
    inventory: &mut RetainedInventory,
    kind: RetainedKind,
    identity: &str,
    count: RetainedCount,
) -> Result<(), StoreError> {
    inventory
        .observe(
            RetainedFormat {
                kind,
                identity: identity.into(),
            },
            count,
        )
        .map_err(|_| StoreError::Capacity)
}
fn formats() -> Vec<RetainedFormat> {
    [
        (RetainedKind::EffectEnvelope, "lsf.effect-record.v1"),
        (RetainedKind::SuccessResult, VALUES),
        (RetainedKind::RejectionResult, VALUES),
        (RetainedKind::CommandFingerprint, VALUES),
        (RetainedKind::CommandAttempt, "lsf.command-record.v3"),
        (RetainedKind::CommandAttempt, "lsf.command-record.v4"),
        (RetainedKind::CommandAttempt, LINKED),
        (RetainedKind::InboxIdentity, LINKED),
        (RetainedKind::OrderingGroup, LINKED),
        (RetainedKind::MigrationCheckpoint, LINKED),
    ]
    .into_iter()
    .map(|(kind, identity)| RetainedFormat {
        kind,
        identity: identity.into(),
    })
    .collect()
}
