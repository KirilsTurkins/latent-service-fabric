use super::*;
use latent_audit::{AuditLimits, DirectoryPhase2AuditJournal};
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
fn recovered_attempt_requires_exact_confirmed_catalog_receipt() {
    runtime().block_on(async {
        for (committed, matching) in [(false, true), (true, true), (true, false)] {
            let mut fixture = Fixture::new().await;
            let prepared = fixture
                .repository
                .prepare_operation(apply("cutpoint", 1))
                .await
                .unwrap();
            let mut expected = mapping::attempt(prepared.preview(), false).unwrap();
            if !matching {
                expected.expected_state_version = Some(0);
            }
            let mut active = fixture
                .audit
                .try_reserve_critical(&expected)
                .unwrap()
                .begin()
                .wait()
                .await
                .unwrap();
            active.mutation_started().unwrap();
            if committed {
                let actual = fixture.repository.commit_operation(prepared).unwrap();
                assert!(actual.value().durability.is_ok());
            } else {
                drop(prepared);
            }
            // Copy only acknowledged files before the terminal owner is lost:
            // this is the process-loss cut, not a forged terminal audit record.
            let copy = fixture.root.path().join("recovered");
            snapshot(&fixture.root.path().join("audit"), &copy);
            drop(active);
            fixture.shutdown();
            let (audit, mut worker) =
                DirectoryPhase2AuditJournal::open(copy, AuditLimits::default()).unwrap();
            reconcile_deployment_audit(&audit, fixture.repository.as_ref(), expires())
                .await
                .unwrap();
            assert_eq!(audit.snapshot().pending_attempts, 0);
            assert_eq!(
                audit.snapshot().unknown_outcomes,
                u64::from(!committed || !matching)
            );
            audit.close();
            assert!(worker.join_until(expires()).unwrap());
        }
    });
}

#[test]
fn expired_reconciliation_rejects_even_an_empty_pending_set() {
    runtime().block_on(async {
        let mut fixture = Fixture::new().await;
        let error = reconcile_deployment_audit(
            &fixture.audit,
            fixture.repository.as_ref(),
            std::time::Instant::now(),
        )
        .await
        .unwrap_err();
        assert_eq!(error.code, PlatformErrorCode::DeadlineExceeded);
        assert_eq!(fixture.audit.snapshot().pending_attempts, 0);
        fixture.shutdown();
    });
}
