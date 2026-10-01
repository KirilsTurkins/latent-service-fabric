use super::{admitted_query, attempt, conclusion, digest, open, query, stop, Directory};
use crate::{
    AuditControlAction, AuditIdentities, AuditLimits, AuditOperationAttempt, AuditRecordData,
    AuditScope, AuditStateTarget,
};
use latent_core::ReleaseDigest;

fn original(action: AuditControlAction) -> AuditOperationAttempt {
    let mut value = attempt();
    value.action = action;
    value.preview_receipt_digest = None;
    value.expected_generation = None;
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
        ..Default::default()
    };
    value
}
#[test]
fn approved_effect_actions_use_real_critical_audit_and_keep_exact_target_after_restart() {
    let directory = Directory::new();
    let path = directory.0.join("effect-audit");
    let (handle, mut worker) = open(&path, AuditLimits::default()).unwrap();
    for (index, action) in [
        AuditControlAction::EffectPlan,
        AuditControlAction::EffectReconcile,
        AuditControlAction::EffectRedrive,
        AuditControlAction::EffectTerminate,
        AuditControlAction::StateOperationRead,
    ]
    .into_iter()
    .enumerate()
    {
        let mut original = original(action);
        original.operation_id = format!("effect-original-{index}");
        let mut done = conclusion();
        done.identities = original.identities.clone();
        handle.preflight_conclusion(&original, &done).unwrap();
        let mut accepted = handle
            .reserve_control_critical(&original)
            .unwrap()
            .begin()
            .blocking_wait()
            .unwrap();
        accepted.mutation_started().unwrap();
        accepted.finish(done).blocking_wait().unwrap();
    }
    stop(&handle, &mut worker);
    drop(worker);
    drop(handle);
    let (handle, mut worker) = open(&path, AuditLimits::default()).unwrap();
    let page = admitted_query(
        &handle,
        &query(original(AuditControlAction::EffectPlan).scope),
    )
    .unwrap()
    .blocking_wait()
    .unwrap();
    assert_eq!(page.records().len(), 10);
    for records in page.records().chunks_exact(2) {
        let AuditRecordData::Attempt(attempt) = &records[0].data else {
            panic!("attempt");
        };
        let AuditRecordData::Outcome { conclusion, .. } = &records[1].data else {
            panic!("outcome");
        };
        assert_eq!(attempt.identities, conclusion.identities);
        assert!(attempt.expected_generation.is_none());
        assert!(attempt.identities.state.is_some());
    }
    drop(page);
    stop(&handle, &mut worker);
}
#[test]
fn effect_audit_rejects_wrong_scope_missing_target_generation_and_reassigned_original() {
    let directory = Directory::new();
    let (handle, mut worker) = open(directory.0.join("audit"), AuditLimits::default()).unwrap();
    let original = original(AuditControlAction::EffectReconcile);
    for case in 0..8 {
        let mut changed = original.clone();
        match case {
            0 => changed.scope = AuditScope::Node,
            1 => changed.identities.state = None,
            2 => changed.identities.component = None,
            3 => changed.identities.publication = None,
            4 => changed.expected_generation = Some(1),
            5 => changed.expected_deployment_generation = Some(1),
            6 => changed.preview_receipt_digest = Some(digest()),
            _ => changed.action = AuditControlAction::Publish,
        }
        assert!(
            handle.reserve_control_critical(&changed).is_err(),
            "attempt {case}"
        );
    }
    let mut done = conclusion();
    done.identities = original.identities.clone();
    handle.preflight_conclusion(&original, &done).unwrap();
    done.identities.state.as_mut().unwrap().incarnation = 2;
    assert!(handle.preflight_conclusion(&original, &done).is_err());
    let page = admitted_query(&handle, &query(original.scope))
        .unwrap()
        .blocking_wait()
        .unwrap();
    assert!(page.records().is_empty());
    drop(page);
    stop(&handle, &mut worker);
}
