use super::*;
use base64::{engine::general_purpose::STANDARD, Engine};
use prost::Message;

fn original() -> c::EffectManagementPlan {
    c::EffectManagementPlan {
        original: Some(c::PlanEffectMutationRequest {
            effect: Some(t::GetEffectRequest {
                profile: Some(latent_rpc::phase4::current_profile()),
                command: Some(t::CommandSelector {
                    namespace: Some(t::NamespaceSelector {
                        tenant: "tenant".into(),
                        namespace: "app".into(),
                        incarnation: "1".into(),
                    }),
                    operation: "save".into(),
                    entity: None,
                    client_key: "original-key".into(),
                    shared_recovery_scope: None,
                }),
                effect_id: "b".repeat(64),
                authorization_publication: Some(c::PublicationRef {
                    id: publication(),
                    tenant: "tenant".into(),
                }),
            }),
            operation_id: "original-effect-stop".into(),
            mutation: c::StateMutationKind::TerminateEffect as i32,
            expected_version: vec![1; 32],
            expected_policy_digest: format!("sha256:{}", "c".repeat(64)),
            reason: "operator reviewed original unknown attempt".into(),
            retry_delay_millis: 0,
        }),
        plan_digest: vec![2; 32],
        management_sequence: 128,
        owner_epoch: u64::MAX,
        claim_generation: 9_007_199_254_740_993,
        dispatch_attempt: 2,
        prepared_at_unix_millis: 10,
        expires_at_unix_millis: 20,
        before: t::EffectDisposition::UncertainAfterDispatch as i32,
        safety: c::EffectPlanSafety::AdministratorDeclared as i32,
        dedup_valid_until_unix_millis: None,
    }
}
fn args(plan: &c::EffectManagementPlan) -> EffectPlanArgs {
    EffectPlanArgs {
        target: target(),
        plan: STANDARD.encode(plan.encode_to_vec()),
    }
}

#[test]
fn effect_apply_and_recovery_preserve_the_original_plan_and_separate_current_read_target() {
    let plan = original();
    let Operation::Phase4(request) =
        prepare_state(&StateCommand::ApplyEffect(args(&plan)), &config()).unwrap()
    else {
        panic!("phase4");
    };
    let Request::MutateState(value) = request.as_ref() else {
        panic!("effect mutation");
    };
    assert_eq!(value.effect_plan.as_ref(), Some(&plan));
    assert_eq!(value.expected_version, vec![1; 32]);
    let data = recovery(&request).unwrap();
    assert_eq!(
        data["originalEffectPlan"]["claimGeneration"],
        "9007199254740993"
    );
    assert_eq!(
        data["originalEffectPlan"]["ownerEpoch"],
        u64::MAX.to_string()
    );
    assert_eq!(data["automaticRetry"], false);
    let mut changed = args(&plan);
    changed.target.authorization_publication = format!("publication:sha256:{}", "d".repeat(64));
    assert!(prepare_state(&StateCommand::ApplyEffect(changed), &config()).is_err());
    let mut changed = args(&plan);
    changed.target.authorization_publication = format!("publication:sha256:{}", "d".repeat(64));
    let Operation::Phase4(request) =
        prepare_state(&StateCommand::EffectOperation(changed), &config()).unwrap()
    else {
        panic!("phase4");
    };
    let Request::GetStateOperationReceipt(value) = request.as_ref() else {
        panic!("recovery");
    };
    assert_eq!(value.original_effect_plan.as_ref(), Some(&plan));
    assert_ne!(
        value.namespace.as_ref().unwrap().authorization_publication,
        plan.original
            .as_ref()
            .unwrap()
            .effect
            .as_ref()
            .unwrap()
            .authorization_publication
    );
}

#[test]
fn effect_plan_input_rejects_oversize_unknown_fields_bad_cas_and_unqualified_delay() {
    let plan = original();
    let mut bad = args(&plan);
    bad.plan = "A".repeat(21_852);
    assert!(prepare_state(&StateCommand::ApplyEffect(bad), &config()).is_err());
    let mut bytes = plan.encode_to_vec();
    bytes.extend_from_slice(&[0x98, 0x06, 0x01]);
    let bad = EffectPlanArgs {
        target: target(),
        plan: STANDARD.encode(bytes),
    };
    assert!(prepare_state(&StateCommand::ApplyEffect(bad), &config()).is_err());
    let mut bad_plan = plan;
    bad_plan
        .original
        .as_mut()
        .unwrap()
        .expected_version
        .truncate(31);
    assert!(prepare_state(&StateCommand::ApplyEffect(args(&bad_plan)), &config()).is_err());
    for delay in [None, Some(0), Some(60_001)] {
        let command = StateCommand::PlanEffect(PlanEffectArgs {
            effect: EffectArgs {
                command: command(),
                effect_id: "b".repeat(64),
            },
            operation_id: "safe-redrive".into(),
            action: EffectMutationAction::Redrive,
            expected_version: STANDARD.encode([1; 32]),
            expected_policy_digest: format!("sha256:{}", "c".repeat(64)),
            reason: "reviewed original".into(),
            retry_delay_millis: delay,
        });
        assert!(prepare_state(&command, &config()).is_err());
    }
}

#[test]
fn expired_historical_effect_plan_projects_losslessly_and_recovers_without_resubmitting() {
    let plan = original();
    let data = projection::effect_plan(&plan);
    assert_eq!(
        data["encodedPlan"]["data"],
        STANDARD.encode(plan.encode_to_vec())
    );
    assert_eq!(
        data["original"]["expectedVersion"]["data"],
        STANDARD.encode([1; 32])
    );
    let Operation::Phase4(request) =
        prepare_state(&StateCommand::EffectOperation(args(&plan)), &config()).unwrap()
    else {
        panic!("phase4");
    };
    assert!(matches!(
        request.as_ref(),
        Request::GetStateOperationReceipt(_)
    ));
    let parsed = Cli::try_parse_from([
        "latent",
        "state",
        "effect-operation",
        "--namespace",
        "app",
        "--incarnation",
        "1",
        "--authorization-publication",
        &publication(),
        "--plan",
        &STANDARD.encode(plan.encode_to_vec()),
    ])
    .unwrap();
    assert!(parsed.validate().is_ok());
    assert!(Cli::try_parse_from([
        "latent",
        "state",
        "apply-effect",
        "--namespace",
        "app",
        "--incarnation",
        "1",
        "--authorization-publication",
        &publication()
    ])
    .is_err());
}
