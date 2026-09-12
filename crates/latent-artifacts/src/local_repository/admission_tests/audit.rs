//! A verified observation does not assert that publication committed.
use super::*;
use crate::{
    AuditedAdmissionAuthority, LifecycleScope, ManagedPublicationUpload, ReleaseActor,
    ReleaseActorKind, ReleaseAuditGuard, ReleaseLifecycleAction, ReleaseMutationContext,
    ReleaseOperationLookup, ReleaseOperationPrecondition,
};
use latent_audit::{
    AuditFilter, AuditLimits, AuditQueryRequest, AuditRecordData, AuditScope,
    DirectoryPhase2AuditJournal, Phase2AuditEventKind,
};
use std::time::{Duration, Instant};

#[test]
fn independent_verification_is_visible_but_unreturnable_publication_has_no_critical_attempt() {
    let root = TempRoot::new();
    let audit_root = TempRoot::new();
    let (audit, mut worker) =
        DirectoryPhase2AuditJournal::open(audit_root.path().join("audit"), AuditLimits::default())
            .unwrap();
    let authority = Authority::new();
    let wrapped = Arc::new(AuditedAdmissionAuthority::new(
        Arc::new(Host(authority)),
        audit.clone(),
    ));
    let repo = DirectoryArtifactRepository::open_enforced(
        root.path(),
        DirectoryArtifactRepositoryConfig::default(),
        AdmissionStorageLimits::default(),
        wrapped,
    )
    .unwrap();
    let context = ReleaseMutationContext {
        scope: LifecycleScope::Tenant(tenant()),
        actor: ReleaseActor {
            subject: "audit-test-admin".to_owned(),
            kind: ReleaseActorKind::Administrator,
        },
        operation: Some(ReleaseOperationPrecondition {
            operation_id: "unreturnable".to_owned(),
            expected_generation: 0,
        }),
    };
    let mut control = ReleaseAuditGuard::new(Some(&audit), ReleaseLifecycleAction::Publish);
    let result = block_on(repo.publish_managed(
        context,
        ManagedPublicationUpload::Package(upload()),
        &mut |preview| {
            let rejected: Result<(), PlatformError> = Err(PlatformError {
                code: PlatformErrorCode::ResourceExhausted,
                message: "test-response-limit".to_owned(),
                retryable: false,
                details: Vec::new(),
            });
            rejected?;
            control.preview(preview)
        },
    ));
    assert!(result.is_err());
    assert!(matches!(
        block_on(repo.get_release_operation(&LifecycleScope::Tenant(tenant()), "unreturnable"))
            .unwrap(),
        ReleaseOperationLookup::Unknown
    ));
    let page = audit
        .query(
            AuditQueryRequest {
                scope: AuditScope::Tenant(tenant()),
                filter: AuditFilter::default(),
                cursor: None,
                limit: 8,
                maximum_bytes: 64 * 1024,
            },
            Instant::now() + Duration::from_secs(5),
        )
        .unwrap()
        .blocking_wait()
        .unwrap();
    assert_eq!(page.records().len(), 1);
    let AuditRecordData::Observation(observation) = &page.records()[0].data else {
        panic!("verification only");
    };
    assert_eq!(observation.kind, Phase2AuditEventKind::VerificationAccepted);
    assert!(observation.identities.package.is_some());
    assert_eq!(audit.snapshot().reserved_records, 0);
    drop(control);
    drop(page);
    audit.close();
    assert!(worker
        .join_until(Instant::now() + Duration::from_secs(5))
        .unwrap());
}
