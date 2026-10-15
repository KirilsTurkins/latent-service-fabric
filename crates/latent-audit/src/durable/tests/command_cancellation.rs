//! One distinct control action, preserving the original action byte spellings.
use super::*;

fn original() -> AuditOperationAttempt {
    let mut value = attempt();
    value.action = AuditControlAction::CommandCancel;
    value.preview_receipt_digest = None;
    value.expected_generation = None;
    value.identities = AuditIdentities {
        publication: Some(
            format!("publication:sha256:{}", "a".repeat(64))
                .parse()
                .unwrap(),
        ),
        component: Some(latent_core::ReleaseDigest(digest().to_string())),
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
fn command_cancel_action_keeps_every_previous_action_encoding() {
    use AuditControlAction as A;
    for (action, bytes) in [
        (A::Publish, "publish"),
        (A::Revoke, "revoke"),
        (A::Retire, "retire"),
        (A::RenewEvidence, "renew-evidence"),
        (A::DeploymentApply, "deployment-apply"),
        (A::DeploymentDelete, "deployment-delete"),
        (A::TriggerApply, "trigger-apply"),
        (A::TriggerDelete, "trigger-delete"),
        (A::Rollout, "rollout"),
        (A::Promotion, "promotion"),
        (A::Rollback, "rollback"),
        (A::CapabilityCall, "capability-call"),
        (A::NamespaceCreate, "namespace-create"),
        (A::NamespaceQuiesce, "namespace-quiesce"),
        (A::NamespaceRetire, "namespace-retire"),
        (A::NamespaceDestroy, "namespace-destroy"),
        (A::NamespaceRecreate, "namespace-recreate"),
        (A::NamespaceInspect, "namespace-inspect"),
        (A::DispatcherInspect, "dispatcher-inspect"),
        (A::DispatcherPause, "dispatcher-pause"),
        (A::DispatcherResume, "dispatcher-resume"),
        (A::DispatcherOperationRead, "dispatcher-operation-read"),
        (A::EffectPlan, "effect-plan"),
        (A::EffectReconcile, "effect-reconcile"),
        (A::EffectRedrive, "effect-redrive"),
        (A::EffectTerminate, "effect-terminate"),
        (A::StateOperationRead, "state-operation-read"),
        (A::StateCheckpoint, "state-checkpoint"),
        (A::PayloadPurge, "payload-purge"),
        (A::CommandFloorRelease, "command-floor-release"),
    ] {
        let expected = format!("\"{bytes}\"");
        assert_eq!(codec::encode(&action, 128).unwrap(), expected.as_bytes());
        assert_eq!(
            codec::decode::<A>(expected.as_bytes(), 128).unwrap(),
            action
        );
    }
    let mut old = original();
    old.action = A::StateOperationRead;
    codec::attempt(&old).unwrap();
    let old_bytes = codec::encode(&old, 4096).unwrap();
    let fixed = codec::encode(&original(), 4096).unwrap();
    assert_eq!(
        String::from_utf8(fixed).unwrap(),
        String::from_utf8(old_bytes)
            .unwrap()
            .replace("\"state-operation-read\"", "\"command-cancel\"")
    );
    assert_eq!(
        codec::decode::<AuditOperationAttempt>(&codec::encode(&original(), 4096).unwrap(), 4096)
            .unwrap(),
        original()
    );
}

#[test]
fn command_cancel_critical_audit_is_durable_and_rejects_reassigned_scope() {
    let directory = Directory::new();
    let path = directory.0.join("command-cancel");
    let (handle, mut worker) = open(&path, AuditLimits::default()).unwrap();
    let original = original();
    for case in 0..5 {
        let mut changed = original.clone();
        match case {
            0 => changed.scope = AuditScope::Node,
            1 => changed.identities.state = None,
            2 => changed.identities.publication = None,
            3 => changed.identities.component = None,
            _ => changed.expected_generation = Some(1),
        }
        assert!(handle.try_reserve_critical(&changed).is_err());
    }
    let mut done = conclusion();
    done.identities = original.identities.clone();
    done.receipt_digest = None;
    handle.preflight_conclusion(&original, &done).unwrap();
    let mut accepted = handle
        .reserve_control_critical(&original)
        .unwrap()
        .begin()
        .blocking_wait()
        .unwrap();
    accepted.mutation_started().unwrap();
    accepted.finish(done).blocking_wait().unwrap();
    stop(&handle, &mut worker);
    drop((handle, worker));
    let (handle, mut worker) = open(&path, AuditLimits::default()).unwrap();
    let page = admitted_query(&handle, &query(original.scope.clone()))
        .unwrap()
        .blocking_wait()
        .unwrap();
    assert_eq!(page.records().len(), 2);
    let AuditRecordData::Attempt(reopened) = &page.records()[0].data else {
        panic!("original attempt absent")
    };
    assert_eq!(reopened, &original);
    let AuditRecordData::Outcome { conclusion, .. } = &page.records()[1].data else {
        panic!("original conclusion absent")
    };
    assert_eq!(conclusion.identities, original.identities);
    assert_eq!(conclusion.result, AuditOperationResult::Committed);
    assert!(!conclusion.replay);
    drop(page);
    stop(&handle, &mut worker);
}
