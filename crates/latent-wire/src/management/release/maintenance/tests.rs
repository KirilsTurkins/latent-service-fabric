use super::*;
use crate::management::ManagementLimits;
use latent_core::{Metadata, PrincipalKind, TenantId};
fn principal() -> InvocationPrincipal {
    InvocationPrincipal {
        subject: "operator".into(),
        kind: PrincipalKind::Administrator,
        tenant: Some(TenantId("tenant".into())),
        service: None,
        claims: Metadata::new(),
    }
}
fn selected() -> proto::PublicationMaintenanceSelection {
    proto::PublicationMaintenanceSelection {
        operation_id: "delete-one".into(),
        catalog_fence: vec![3; 32],
        targets: vec![proto::PublicationMaintenanceTarget {
            publication: Some(proto::PublicationRef {
                id: format!("publication:sha256:{}", "a".repeat(64)),
                tenant: "tenant".into(),
            }),
            expected_generation: 2,
        }],
    }
}
fn check(
    v: proto::PublicationMaintenanceSelection,
) -> Result<latent_artifacts::PublicationDeletionRequest, Status> {
    let l = ManagementLimits::default();
    validation::selection(
        Some(&v),
        &principal(),
        &mut RequestBudget::new::<proto::PublicationMaintenanceSelection>(&l).unwrap(),
        &l,
    )
}
#[test]
fn publication_maintenance_selection_derives_actor_and_rejects_foreign_or_duplicate_authority() {
    let v = check(selected()).unwrap();
    assert_eq!(v.actor.subject, "operator");
    assert_eq!(
        v.actor.kind,
        latent_artifacts::ReleaseActorKind::Administrator
    );
    let mut foreign = selected();
    foreign.targets[0].publication.as_mut().unwrap().tenant = "other".into();
    assert!(check(foreign).is_err());
    let mut duplicate = selected();
    duplicate.targets.push(duplicate.targets[0].clone());
    assert!(check(duplicate).is_err());
    let mut absent = selected();
    absent.targets[0].publication = None;
    assert!(check(absent).is_err());
}
#[test]
fn publication_maintenance_enforces_exact_batch_fence_generation_and_work_limits() {
    for n in [0, 31, 33] {
        let mut v = selected();
        v.catalog_fence = vec![0; n];
        assert!(check(v).is_err());
    }
    let mut spare = selected();
    spare.catalog_fence.reserve(32);
    assert!(check(spare).is_err());
    let mut zero = selected();
    zero.targets[0].expected_generation = 0;
    assert!(check(zero).is_err());
    let mut empty = selected();
    empty.targets.clear();
    assert!(check(empty).is_err());
    let mut many = selected();
    many.targets = vec![many.targets[0].clone(); 33];
    assert!(check(many).is_err());
    for (f, b) in [(0, 1), (1025, 1), (1, 0), (1, 1073741825)] {
        assert!(validation::work(f, b).is_err());
    }
    assert!(validation::work(1024, 1073741824).is_ok());
}
#[test]
fn publication_maintenance_nonreclamation_commands_refuse_hidden_cleanup_parameters() {
    let l = ManagementLimits::default();
    for kind in [
        proto::PublicationMaintenanceKind::Pin,
        proto::PublicationMaintenanceKind::Unpin,
        proto::PublicationMaintenanceKind::Delete,
    ] {
        for (files, bytes, fence) in [(1, 0, vec![]), (0, 1, vec![]), (0, 0, vec![1; 32])] {
            let c = proto::PublicationMaintenanceCommand {
                kind: kind as i32,
                selection: Some(selected()),
                maximum_files: files,
                maximum_bytes_hashed: bytes,
                reclamation_catalog_fence: fence,
            };
            assert!(validation::command(
                Some(&c),
                &principal(),
                &mut RequestBudget::new::<proto::MaintainPublicationsRequest>(&l).unwrap(),
                &l
            )
            .is_err());
        }
    }
    assert!(validation::kind(0).is_err());
    assert!(validation::kind(i32::MAX).is_err());
}
#[test]
fn publication_maintenance_deadline_never_renews_expired_transport_authority() {
    let mut request = Request::new(());
    let context = crate::invocation::AuthenticatedInvocationContext::new(principal())
        .with_transport_deadline_at(1, Instant::now() - Duration::from_secs(1));
    request.extensions_mut().insert(context);
    assert!(deadline(&request, 0).is_err());
    assert!(deadline(&request, 30001).is_err());
    assert!(remaining(Instant::now() - Duration::from_secs(1)).is_err());
    assert!(remaining(deadline(&request, 30000).unwrap()).is_err());
}
