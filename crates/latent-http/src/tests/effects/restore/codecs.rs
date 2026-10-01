//! Installed finite synthetic decoder/artifact closure. Unknown formats fail;
//! current source declarations never certify another publication or Java guest.
use super::*;
use latent_state::{
    embedded::{Family, ReadView, RowKey},
    namespace::{
        catalog::NamespaceCatalog,
        compatibility::{RetainedCount, RetainedFormat, RetainedInventory, RetainedKind, SchemaId},
    },
    recovery::{
        offline::RecoveryCodecs,
        resume::{NamespaceResumeReceipt, RECEIPT_PREFIX},
        snapshot::{RequiredArtifact, SnapshotClosure, SnapshotMetadata},
        RecoveryGuard,
    },
};
use sha2::{Digest, Sha256};

mod review;

const DEFINITION: &[u8] = include_bytes!(concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../contracts/state/application-aggregate-v1.schema.json"
));
const COMPONENT: &[u8] = b"\0asm\r\0\x01\0";
const CONTRACT: &[u8] = b"latent.http-restore-fixture.v1:synthetic-command;input=latent.http-restore.input.v1;result=latent.http-restore.result.v1:count=7;no-guest-execution";
const FAMILIES: [Family; 10] = [
    Family::Namespace,
    Family::State,
    Family::Tombstone,
    Family::Command,
    Family::Result,
    Family::Outbox,
    Family::Attempt,
    Family::Inbox,
    Family::PayloadReference,
    Family::Maintenance,
];

pub(super) struct Codecs {
    pub authority: DurableEffectAuthority,
    pub owner: EffectAuthorityOwner,
    pub clock: Arc<Clock>,
    pub artifacts: Vec<RequiredArtifact>,
    pub formats: Vec<RetainedFormat>,
    source: latent_commit::atomic::SourceIdentity,
    reconciliation: std::sync::Mutex<Option<(RecoveryGuard, [u8; 32])>>,
}

impl Codecs {
    pub(super) fn new(fixture: &Fixture, workload: &command::Workload) -> Arc<Self> {
        let profile_bytes = serde_json::to_vec(workload.authority.profile()).unwrap();
        let mut artifacts = vec![
            schema_artifact(),
            component_artifact(),
            contract_artifact(),
            artifact(workload.authority.scope().publication.clone(), COMPONENT),
            artifact(
                "latent.http-effect.put-once.v1.profile".into(),
                &profile_bytes,
            ),
        ];
        artifacts.sort_by(|a, b| a.identity.cmp(&b.identity));
        Arc::new(Self {
            authority: workload.authority.clone(),
            owner: fixture.authority.clone(),
            clock: fixture.clock.clone(),
            artifacts,
            formats: vec![
                format(RetainedKind::CommandFingerprint, "lsf.command-record.v3"),
                format(RetainedKind::CommandAttempt, "lsf.command-record.v3"),
                format(RetainedKind::CommandAttempt, "lsf.dispatch-history.v1"),
                format(RetainedKind::SuccessResult, "lsf.command-result.v3"),
                format(RetainedKind::InboxIdentity, "lsf.inbox-identity.v1"),
                format(RetainedKind::EffectEnvelope, "lsf.effect-record.v1"),
                format(RetainedKind::EffectPayload, "lsf.effect-payload.v1"),
                format(
                    RetainedKind::AdapterProfile,
                    fixture.adapter.profile().idempotency_profile.as_str(),
                ),
                latent_state::recovery::resume::retained_format(),
            ],
            source: latent_commit::atomic::CommandRecord::decode(&workload.command)
                .unwrap()
                .source()
                .clone(),
            reconciliation: std::sync::Mutex::new(None),
        })
    }

    pub(super) fn metadata(&self) -> SnapshotMetadata {
        SnapshotMetadata {
            tenant: "a".into(),
            operation_id: "backup-before-remote-apply".into(),
            operator_id: "operator".into(),
            runtime_digest: self.runtime_digest(),
            decoder_formats: self.formats.clone(),
            required_artifacts: self.artifacts.clone(),
        }
    }

    pub(super) fn validate(view: &ReadView) -> Result<(), StoreError> {
        latent_commit::atomic::validate_view(view, foreign)?;
        DispatchCatalog::validate_view(view)
    }
}

impl RecoveryCodecs for Codecs {
    fn runtime_digest(&self) -> [u8; 32] {
        Sha256::digest(b"latent.http-restore-runtime.v1:LCM3/LCR3/LIC1/LER1/LEP1/LEV1/LDI1/LDH1/LDO1/NSH1/NV2/SV2/NRS1").into()
    }
    fn retained_bytes(&self) -> u64 {
        32 * 1024
    }
    fn scratch_bytes(&self) -> u64 {
        4 * 1024 * 1024
    }
    fn installed_formats(&self) -> &[RetainedFormat] {
        &self.formats
    }
    fn validate_row(
        &self,
        source: &ReadView,
        key: &RowKey,
        value: &[u8],
    ) -> Result<(), StoreError> {
        match latent_commit::atomic::validate_row(key, value) {
            Err(StoreError::UnsupportedFormat) => foreign(source, key, value),
            result => result,
        }
    }
    fn validate_view(&self, view: &ReadView) -> Result<SnapshotClosure, StoreError> {
        Self::validate(view)?;
        let mut inventory = RetainedInventory::default();
        let mut totals = (0_u64, 0_u64);
        for family in FAMILIES {
            let mut resume = None;
            loop {
                let page = view.scan_after(family, b"", resume.as_deref(), 128, 4 * 1024 * 1024)?;
                for (key, bytes) in page.rows {
                    totals.0 = totals.0.checked_add(1).ok_or(StoreError::Capacity)?;
                    totals.1 = totals
                        .1
                        .checked_add((key.key.len() + bytes.len()) as u64)
                        .ok_or(StoreError::Capacity)?;
                    if totals.0 > 65_536 || totals.1 > 128 * 1024 * 1024 {
                        return Err(StoreError::Capacity);
                    }
                    self.require_original_source(&key, &bytes)?;
                    observe(&mut inventory, &key, &bytes, &self.authority)?;
                }
                resume = page.resume;
                if resume.is_none() {
                    break;
                }
            }
        }
        inventory
            .require_decoders(&self.formats)
            .map_err(|_| StoreError::UnsupportedFormat)?;
        Ok(SnapshotClosure {
            inventory,
            required_artifacts: self.artifacts.clone(),
        })
    }
    fn verify_artifact(&self, artifact: &RequiredArtifact) -> Result<(), StoreError> {
        if self.artifacts.contains(artifact) {
            Ok(())
        } else {
            Err(StoreError::UnsupportedFormat)
        }
    }
    // The installed review implementation contains no guest/provider execution.
    // Current rule, continuity and exact original effect checks are local only.
    fn review_backup(
        &self,
        view: &ReadView,
        metadata: &SnapshotMetadata,
        _: &SnapshotFile,
    ) -> Result<(), StoreError> {
        self.check_operator(&metadata.operator_id)?;
        self.validate_view(view)?.require_declared(metadata)
    }
    fn authorize_inspection(
        &self,
        _: &ReadView,
        request: &OfflineRestoreRequest,
    ) -> Result<(), StoreError> {
        self.check_operator(&request.review.operator_id)
    }
    fn review_restore(
        &self,
        view: &ReadView,
        window: &latent_state::recovery::restore::RestoreWindow,
        request: &OfflineRestoreRequest,
    ) -> Result<(), StoreError> {
        self.authorize_inspection(view, request)?;
        if request.review.window_acknowledgement != window.digest()? {
            return Err(StoreError::Conflict);
        }
        self.validate_view(view)?;
        Ok(())
    }
    fn review_reconciliation(
        &self,
        view: &ReadView,
        request: &RecoveryReviewRequest,
    ) -> Result<(), StoreError> {
        review::reconcile(self, view, request)
    }
    fn accept_reconciliation(&self, request: &RecoveryReviewRequest) -> Result<(), StoreError> {
        self.check_reconciliation(request)
    }
    fn review_namespace_resume(
        &self,
        view: &ReadView,
        request: &NamespaceResumeRequest,
        observed: latent_state::recovery::resume::NamespaceResumeObservation<'_>,
    ) -> Result<(), StoreError> {
        review::resume(self, view, request, observed)
    }
    fn accept_namespace_resume(&self, request: &NamespaceResumeRequest) -> Result<(), StoreError> {
        self.check_review(&request.operator_id, request.review_digest, [71; 32])
    }
    fn authorize_namespace_inspection(
        &self,
        _: &ReadView,
        operator: &str,
        namespace: &latent_core::StateNamespaceId,
    ) -> Result<(), StoreError> {
        self.check_operator(operator)?;
        if namespace.0 == "orders" {
            Ok(())
        } else {
            Err(StoreError::Conflict)
        }
    }
}

impl Codecs {
    fn require_original_source(&self, key: &RowKey, bytes: &[u8]) -> Result<(), StoreError> {
        if key.family == Family::Command
            || (key.family == Family::Attempt && key.key.starts_with(b"command-attempt-v1\0"))
        {
            let record = latent_commit::atomic::CommandRecord::decode(bytes)
                .map_err(|_| StoreError::Corrupt)?;
            if record.source() != &self.source
                || record.key().tenant != "a"
                || record.key().namespace != "orders"
                || record.key().incarnation != "7"
            {
                return Err(StoreError::UnsupportedFormat);
            }
        }
        if key.family == Family::Result {
            // This fixture installs the full success-result v3 decoder only.
            // It never relabels pending/expired/rejection bytes as that format.
            let result = latent_commit::atomic::DurableResult::decode(bytes)
                .map_err(|_| StoreError::UnsupportedFormat)?;
            if result.value() != Some(&command::value(b"count=7")) || result.code().is_some() {
                return Err(StoreError::UnsupportedFormat);
            }
        }
        Ok(())
    }
}

fn foreign(view: &ReadView, key: &RowKey, value: &[u8]) -> Result<(), StoreError> {
    if *key == latent_state::recovery::guard_key() {
        RecoveryGuard::validate_row(key, value)
    } else if key.family == Family::Maintenance && key.key.starts_with(RECEIPT_PREFIX) {
        NamespaceResumeReceipt::validate_row(key, value)
    } else if key.family == Family::Namespace {
        NamespaceCatalog::validate_row(key, value).map_err(|_| StoreError::Corrupt)
    } else {
        match latent_effects::dispatch_store::validate_row(key, value) {
            Err(StoreError::UnsupportedFormat) => {
                latent_state::session::validate_row(view, key, value)
            }
            result => result,
        }
    }
}

fn observe(
    inventory: &mut RetainedInventory,
    key: &RowKey,
    bytes: &[u8],
    authority: &DurableEffectAuthority,
) -> Result<(), StoreError> {
    let known = match key.family {
        Family::Command => Some(format(
            RetainedKind::CommandFingerprint,
            "lsf.command-record.v3",
        )),
        Family::Attempt if key.key.starts_with(b"command-attempt-v1\0") => Some(format(
            RetainedKind::CommandAttempt,
            "lsf.command-record.v3",
        )),
        Family::Attempt => Some(format(
            RetainedKind::CommandAttempt,
            "lsf.dispatch-history.v1",
        )),
        Family::Result => Some(format(RetainedKind::SuccessResult, "lsf.command-result.v3")),
        Family::Inbox => Some(format(RetainedKind::InboxIdentity, "lsf.inbox-identity.v1")),
        Family::Outbox => Some(format(RetainedKind::EffectEnvelope, "lsf.effect-record.v1")),
        Family::PayloadReference => {
            Some(format(RetainedKind::EffectPayload, "lsf.effect-payload.v1"))
        }
        Family::Maintenance if key.key.starts_with(RECEIPT_PREFIX) => {
            Some(latent_state::recovery::resume::retained_format())
        }
        _ => None,
    };
    let count = RetainedCount {
        rows: 1,
        bytes: (key.key.len() + bytes.len()) as u64,
        unresolved: u64::from(
            key.family == Family::Outbox
                && !EffectRecord::decode(bytes)
                    .map_err(|_| StoreError::Corrupt)?
                    .disposition()
                    .terminal(),
        ),
    };
    if let Some(format) = known {
        inventory
            .observe(format, count)
            .map_err(|_| StoreError::Capacity)?;
    }
    if key.family == Family::Outbox {
        let actual = EffectRecord::decode(bytes)
            .map_err(|_| StoreError::Corrupt)?
            .authority()
            .map_err(|_| StoreError::Corrupt)?;
        if &actual != authority {
            return Err(StoreError::Conflict);
        }
        inventory
            .observe(
                format(
                    RetainedKind::AdapterProfile,
                    &actual.profile().idempotency_profile,
                ),
                count,
            )
            .map_err(|_| StoreError::Capacity)?;
    }
    Ok(())
}

fn format(kind: RetainedKind, identity: &str) -> RetainedFormat {
    RetainedFormat {
        kind,
        identity: identity.into(),
    }
}
fn artifact(identity: String, bytes: &[u8]) -> RequiredArtifact {
    RequiredArtifact {
        identity,
        digest: Sha256::digest(bytes).into(),
    }
}
pub(super) fn schema_artifact() -> RequiredArtifact {
    artifact(
        SchemaId::from_definition(DEFINITION)
            .unwrap()
            .as_str()
            .into(),
        DEFINITION,
    )
}
pub(super) fn component_artifact() -> RequiredArtifact {
    artifact(latent_artifacts::content_digest(COMPONENT).0, COMPONENT)
}
pub(super) fn contract_artifact() -> RequiredArtifact {
    artifact(latent_artifacts::content_digest(CONTRACT).0, CONTRACT)
}
