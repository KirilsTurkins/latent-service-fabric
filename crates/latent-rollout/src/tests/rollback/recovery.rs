use super::*;
use latent_control_store::DeploymentStore;
use latent_core::DeploymentId;
use std::os::unix::fs::PermissionsExt;

fn snapshot(from: &std::path::Path, to: &std::path::Path) {
    std::fs::create_dir(to).unwrap();
    std::fs::set_permissions(to, std::fs::Permissions::from_mode(0o700)).unwrap();
    std::fs::create_dir(to.join("records")).unwrap();
    std::fs::set_permissions(to.join("records"), std::fs::Permissions::from_mode(0o700)).unwrap();
    for name in ["MODE", "HEAD"] {
        std::fs::copy(from.join(name), to.join(name)).unwrap();
    }
    let entries: Vec<_> = std::fs::read_dir(from.join("records")).unwrap().collect();
    assert!(entries.len() <= 8);
    for entry in entries {
        let entry = entry.unwrap();
        assert!(entry.file_type().unwrap().is_file());
        std::fs::copy(entry.path(), to.join("records").join(entry.file_name())).unwrap();
    }
}

#[test]
fn rollback_audit_recovery_requires_exact_committed_target() {
    runtime().block_on(async {
        for (committed, matching) in [(false, true), (true, true), (true, false)] {
            let (mut fixture, _gate) = support::fixture(false).await;
            support::start(&fixture, false).await;
            drop(support::rows(&fixture).await);
            let prepared = fixture
                .repository
                .prepare_rollout(request("restore", 1, 1))
                .await
                .unwrap();
            let mut description = audit::attempt(prepared.preview(), false).unwrap();
            if !matching {
                description.expected_rollback_target_generation = Some(RouteGeneration(2));
            }
            let mut active = fixture
                .audit
                .try_reserve_critical(&description)
                .unwrap()
                .begin()
                .wait()
                .await
                .unwrap();
            active.mutation_started().unwrap();
            if committed {
                fixture
                    .repository
                    .commit_rollout(prepared)
                    .unwrap()
                    .durability
                    .unwrap();
            } else {
                drop(prepared);
            }
            let copy = fixture.root.path().join("rollback-recovered");
            snapshot(&fixture.root.path().join("audit"), &copy);
            drop(active);
            fixture.shutdown().await;
            let (recovered, mut worker) =
                DirectoryPhase2AuditJournal::open(copy, AuditLimits::default()).unwrap();
            reconcile_rollout_audit(&recovered, &fixture.repository, expires())
                .await
                .unwrap();
            assert_eq!(recovered.snapshot().pending_attempts, 0);
            assert_eq!(
                recovered.snapshot().unknown_outcomes,
                u64::from(!committed || !matching)
            );
            recovered.close();
            assert!(worker.join_until(expires()).unwrap());
        }
    });
}

#[test]
fn concurrent_manual_write_wins_over_prepared_rollback_without_partial_history() {
    runtime().block_on(async {
        let (mut fixture, _gate) = support::fixture(false).await;
        support::start(&fixture, false).await;
        let (entered, ready) = std::sync::mpsc::sync_channel(1);
        let (release, proceed) = std::sync::mpsc::sync_channel(1);
        let pending = fixture
            .handle
            .rollback(request("racing", 1, 1), expires(), move |_| {
                entered.send(()).unwrap();
                proceed
                    .recv_timeout(Duration::from_secs(5))
                    .map_err(|_| closed())?;
                Ok(())
            })
            .unwrap();
        ready.recv_timeout(Duration::from_secs(5)).unwrap();
        let base = DeploymentId("base".into());
        let mut manual = fixture.repository.get(&base).await.unwrap().unwrap();
        manual.route_weight = 8000;
        fixture.repository.apply(manual.clone()).await.unwrap();
        release.send(()).unwrap();
        let failure = pending.wait().await.err().unwrap();
        assert_eq!(failure.error.code, PlatformErrorCode::StateConflict);
        assert_eq!(
            fixture.repository.get(&base).await.unwrap().unwrap(),
            manual
        );
        assert!(fixture
            .repository
            .get(&DeploymentId("candidate".into()))
            .await
            .unwrap()
            .is_some());
        let status = fixture
            .repository
            .get_rollout(&TenantId("alice".into()), &RolloutId("rollout".into()))
            .unwrap()
            .unwrap();
        assert_eq!(status.revision, 1);
        assert_ne!(status.state, RolloutState::RolledBack);
        fixture.shutdown().await;
    });
}
