use super::{admitted_query, attempt, conclusion, digest, open, query, stop, Directory};
use crate::{
    AuditControlAction, AuditIdentities, AuditLimits, AuditOperationAttempt, AuditRecordData,
    AuditScope, AuditStateTarget,
};
use latent_core::ReleaseDigest;

fn namespace_attempt() -> AuditOperationAttempt {
    let mut value = attempt();
    value.action = AuditControlAction::NamespaceCreate;
    value.preview_receipt_digest = None;
    value.operation_id = "n".repeat(256);
    value.identities = AuditIdentities {
        publication: Some(
            format!("publication:sha256:{}", "a".repeat(64))
                .parse()
                .unwrap(),
        ),
        component: Some(ReleaseDigest(digest().to_string())),
        state: Some(AuditStateTarget {
            namespace: "orders".into(),
            incarnation: 1,
            state_schema: digest(),
        }),
        ..AuditIdentities::default()
    };
    value
}

#[test]
fn namespace_audit_original_target_and_maximum_operation_survive_restart() {
    let directory = Directory::new();
    let path = directory.0.join("namespace-audit");
    let original = namespace_attempt();
    let (handle, mut worker) = open(&path, AuditLimits::default()).unwrap();
    // Existing records retain their original format without a synthetic state target.
    for value in [&attempt(), &original] {
        let mut done = conclusion();
        done.identities = value.identities.clone();
        handle.preflight_conclusion(value, &done).unwrap();
        let mut guard = handle
            .reserve_control_critical(value)
            .unwrap()
            .begin()
            .blocking_wait()
            .unwrap();
        guard.mutation_started().unwrap();
        guard.finish(done).blocking_wait().unwrap();
    }
    stop(&handle, &mut worker);
    drop(worker);
    drop(handle);
    let (handle, mut worker) = open(&path, AuditLimits::default()).unwrap();
    let page = admitted_query(&handle, &query(original.scope.clone()))
        .unwrap()
        .blocking_wait()
        .unwrap();
    assert_eq!(page.records().len(), 4);
    let AuditRecordData::Attempt(value) = &page.records()[2].data else {
        panic!("attempt")
    };
    assert_eq!(value.operation_id, original.operation_id);
    assert_eq!(value.identities, original.identities);
    let AuditRecordData::Outcome { conclusion, .. } = &page.records()[3].data else {
        panic!("outcome")
    };
    assert_eq!(conclusion.identities, original.identities);
    drop(page);
    stop(&handle, &mut worker);
}

#[test]
fn namespace_audit_rejects_node_scope_hybrids_and_reassigned_terminal_target() {
    let directory = Directory::new();
    let (handle, mut worker) = open(directory.0.join("audit"), AuditLimits::default()).unwrap();
    let original = namespace_attempt();
    for case in 0..5 {
        let mut invalid = original.clone();
        match case {
            0 => invalid.scope = AuditScope::Node,
            1 => invalid.identities.state = None,
            2 => invalid.identities.component = None,
            3 => invalid.expected_generation = None,
            _ => invalid.action = AuditControlAction::Publish,
        }
        assert!(
            handle.reserve_control_critical(&invalid).is_err(),
            "attempt {case}"
        );
    }
    let mut done = conclusion();
    done.identities = original.identities.clone();
    handle.preflight_conclusion(&original, &done).unwrap();
    for case in 0..5 {
        let mut changed = done.clone();
        match case {
            0 => changed.identities.state.as_mut().unwrap().namespace = "another".into(),
            1 => changed.identities.state.as_mut().unwrap().incarnation = 2,
            2 => {
                changed.identities.state.as_mut().unwrap().state_schema =
                    format!("sha256:{}", "b".repeat(64)).parse().unwrap();
            }
            3 => changed.identities.state = None,
            _ => {
                changed.identities.component =
                    Some(ReleaseDigest(format!("sha256:{}", "b".repeat(64))));
            }
        }
        assert!(
            handle.preflight_conclusion(&original, &changed).is_err(),
            "terminal {case}"
        );
    }
    let page = admitted_query(&handle, &query(original.scope))
        .unwrap()
        .blocking_wait()
        .unwrap();
    assert!(page.records().is_empty());
    drop(page);
    stop(&handle, &mut worker);
}
