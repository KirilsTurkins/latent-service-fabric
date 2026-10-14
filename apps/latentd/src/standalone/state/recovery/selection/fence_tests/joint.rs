//! Joint API controls retain each real sealed owner, including Restore's second purpose.
use super::Fixture;
use latent_artifacts::ReleaseUseEligibility;

fn dependencies(fixture: &Fixture) -> Vec<ReleaseUseEligibility> {
    fixture
        .codecs
        .catalog
        .schemas
        .iter()
        .map(|row| row.operation.publication().clone())
        .collect()
}

#[tokio::test]
async fn second_original_restore_decision_revision_remains_required_in_joint_fence() {
    let fixture = Fixture::new(true).await;
    let first = fixture.captured("native", "namespace-inspect-restore");
    let second = fixture.captured("native-secondary", "namespace-restore");
    let dependencies = dependencies(&fixture);
    let mut calls = 0;
    fixture
        .policy
        .with_retained_decisions_and_dependencies(
            &[&first, &second],
            &dependencies,
            &mut |inputs| {
                assert_eq!(inputs.len(), 2);
                assert_eq!(inputs[0].operation, "namespace-inspect-restore");
                assert_eq!(inputs[1].operation, "namespace-restore");
                fixture.codecs.original.with_live(|| ()).unwrap();
                calls += 1;
                Ok(())
            },
        )
        .unwrap();
    assert_eq!(calls, 1);
    fixture.revoke_policy(true, false);
    fixture
        .policy
        .with_retained_decision(&first, &mut |_, _| Ok(()))
        .unwrap();
    assert!(fixture
        .policy
        .with_retained_decisions_and_dependencies(&[&first, &second], &dependencies, &mut |_| {
            calls += 1;
            Ok(())
        })
        .is_err());
    assert_eq!(calls, 1);
    drop((first, second, dependencies));
    fixture.finish().await;
}

#[tokio::test]
async fn joint_fence_rejects_revoked_signed_decoder_even_when_primary_decision_is_current() {
    let fixture = Fixture::new(false).await;
    let captured = fixture.captured("native", "namespace-resume");
    let dependencies = dependencies(&fixture);
    fixture.revoke_publication(true);
    fixture
        .policy
        .with_retained_decision(&captured, &mut |_, _| Ok(()))
        .unwrap();
    let mut called = false;
    assert!(fixture
        .policy
        .with_retained_decisions_and_dependencies(&[&captured], &dependencies, &mut |_| {
            called = true;
            Ok(())
        })
        .is_err());
    assert!(!called);
    drop((captured, dependencies));
    fixture.finish().await;
}

#[tokio::test]
async fn joint_fence_rejects_actual_foreign_policy_and_catalog_owners() {
    let fixture = Fixture::new(false).await;
    let foreign = Fixture::new(false).await;
    let captured = fixture.captured("native", "namespace-resume");
    let foreign_captured = foreign.captured("native", "namespace-resume");
    let selected_dependencies = dependencies(&fixture);
    let foreign_dependencies = dependencies(&foreign);
    let mut called = false;
    assert!(fixture
        .policy
        .with_retained_decisions_and_dependencies(
            &[&foreign_captured],
            &selected_dependencies,
            &mut |_| {
                called = true;
                Ok(())
            }
        )
        .is_err());
    assert!(fixture
        .policy
        .with_retained_decisions_and_dependencies(&[&captured], &foreign_dependencies, &mut |_| {
            called = true;
            Ok(())
        })
        .is_err());
    assert!(!called);
    drop((
        captured,
        foreign_captured,
        selected_dependencies,
        foreign_dependencies,
    ));
    fixture.finish().await;
    foreign.finish().await;
}

#[tokio::test]
async fn joint_fence_rejects_authentic_same_catalog_foreign_tenant_dependency() {
    let fixture = Fixture::new(false).await;
    let captured = fixture.captured("native", "namespace-resume");
    let foreign = fixture.foreign_tenant_dependency().await;
    foreign
        .check_for_catalog(&fixture.artifacts.lifecycle_authority())
        .unwrap();
    assert_eq!(
        foreign.tenant(),
        Some(&latent_core::TenantId("other".into()))
    );
    let mut called = false;
    assert!(fixture
        .policy
        .with_retained_decisions_and_dependencies(&[&captured], &[foreign], &mut |_| {
            called = true;
            Ok(())
        })
        .is_err());
    assert!(!called);
    drop(captured);
    fixture.finish().await;
}

#[tokio::test]
async fn joint_fence_never_truncates_original_retained_decisions_or_dependency_bounds() {
    let fixture = Fixture::new(false).await;
    let captured = fixture.captured("native", "namespace-resume");
    let dependency = fixture
        .codecs
        .catalog
        .primary()
        .operation
        .publication()
        .clone();
    let mut calls = 0;
    fixture
        .policy
        .with_retained_decisions_and_dependencies(
            &[&captured; 8],
            &vec![dependency.clone(); 11],
            &mut |_| {
                calls += 1;
                Ok(())
            },
        )
        .unwrap();
    assert_eq!(calls, 1);
    for (decisions, sources) in [
        (Vec::new(), Vec::new()),
        (vec![&captured; 9], Vec::new()),
        (vec![&captured], vec![dependency.clone(); 12]),
    ] {
        let mut called = false;
        assert!(fixture
            .policy
            .with_retained_decisions_and_dependencies(&decisions, &sources, &mut |_| {
                called = true;
                Ok(())
            })
            .is_err());
        assert!(!called);
    }
    drop((captured, dependency));
    fixture.finish().await;
}
