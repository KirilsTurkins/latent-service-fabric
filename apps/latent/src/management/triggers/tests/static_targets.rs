use super::*;

fn current(application: bool) -> proto::TriggerOperationReceipt {
    let mut value = receipt();
    let target = value.target.take().unwrap();
    value.target = Some(if application {
        target
    } else {
        proto::TriggerReceiptTarget {
            publication: target.publication,
            kind: proto::TriggerReceiptTargetKind::StaticWeb as i32,
            web_manifest_digest: value.manifest_digest.clone(),
            assets_digest: value.manifest_digest.clone(),
            web_generation: u64::MAX,
            ..Default::default()
        }
    });
    if !application {
        value.route_generation = 0;
    }
    value.format_version = 2;
    value
}

#[test]
fn v2_application_and_static_receipts_project_exact_disjoint_targets() {
    for application in [false, true] {
        let original = current(application);
        let decoded = <proto::TriggerOperationReceipt as prost::Message>::decode(
            prost::Message::encode_to_vec(&original).as_slice(),
        )
        .unwrap();
        response::receipt_scope(&decoded, "tenant-a", "create", Some("web")).unwrap();
        let projected = decoded.project();
        assert!(projected.get("publication").is_none());
        assert!(projected.get("componentDigest").is_none());
        assert_eq!(projected["target"]["publication"]["tenant"], "tenant-a");
        if application {
            assert_eq!(projected["target"]["kind"], "application");
            assert!(projected["target"].get("webGeneration").is_none());
        } else {
            assert_eq!(projected["target"]["kind"], "static-web");
            assert_eq!(projected["target"]["webGeneration"], u64::MAX.to_string());
            for field in [
                "componentDigest",
                "deploymentId",
                "deploymentGeneration",
                "revision",
            ] {
                assert!(projected["target"].get(field).is_none());
            }
        }
    }
}

#[test]
fn v2_receipts_reject_hybrids_foreign_scope_and_incomplete_target_identity() {
    for mutate in [
        (|v: &mut proto::TriggerOperationReceipt| v.format_version = 1)
            as fn(&mut proto::TriggerOperationReceipt),
        |v| v.target = None,
        |v| {
            v.target
                .as_mut()
                .unwrap()
                .publication
                .as_mut()
                .unwrap()
                .tenant = "foreign".into();
        },
        |v| v.target.as_mut().unwrap().kind = 999,
        |v| v.target.as_mut().unwrap().web_generation = 0,
        |v| v.target.as_mut().unwrap().assets_digest = "sha256:invalid".into(),
        |v| v.target.as_mut().unwrap().web_manifest_digest.clear(),
        |v| v.target.as_mut().unwrap().deployment_generation = 1,
    ] {
        let mut value = current(false);
        mutate(&mut value);
        assert!(projection::checked(&value, 4096).is_err());
    }
    let mut application = current(true);
    application.target.as_mut().unwrap().web_generation = 1;
    assert!(projection::checked(&application, 4096).is_err());
    application.target.as_mut().unwrap().web_generation = 0;
    application.target.as_mut().unwrap().deployment_generation = application.route_generation + 1;
    assert!(projection::checked(&application, 4096).is_err());
}

#[test]
fn apply_receipts_match_variant_publication_and_application_revision() {
    for application in [false, true] {
        let value = current(application);
        let target = value.target.as_ref().unwrap();
        let expected = proto::TriggerTarget {
            kind: if application {
                proto::TriggerTargetKind::Application
            } else {
                proto::TriggerTargetKind::StaticWeb
            } as i32,
            publication: target.publication.clone(),
            route: application.then(|| target.deployment_id.clone()),
            revision: application.then(|| target.revision.clone()),
            deployment_generation: application.then_some(target.deployment_generation),
            ..Default::default()
        };
        assert!(response::target_matches(&value, &expected));
        assert_eq!(response::target_matches(&receipt(), &expected), application);
        for kind in [proto::TriggerTargetKind::Unspecified as i32, 999] {
            let mut invalid = expected.clone();
            invalid.kind = kind;
            assert!(!response::target_matches(&value, &invalid));
        }
        let mut changed = expected.clone();
        changed.kind = if application { 2 } else { 1 };
        assert!(!response::target_matches(&value, &changed));
        changed = expected;
        changed.publication.as_mut().unwrap().tenant = "foreign".into();
        assert!(!response::target_matches(&value, &changed));
    }
}

#[test]
fn static_manifest_prepares_and_roundtrips_without_application_identity() {
    let mut value = manifest();
    value["spec"]["target"] = json!({"kind":"static-web",
        "publication":format!("publication:sha256:{}", "a".repeat(64))});
    value["spec"]["configuration"]["profile"] = json!("static-site-v1");
    let directory = tempfile::tempdir().unwrap();
    let file = directory.path().join("trigger.json");
    std::fs::write(&file, serde_json::to_vec(&value).unwrap()).unwrap();
    let command = TriggerCommand::Apply {
        file,
        mutation: TriggerMutation {
            operation_id: "create-static".into(),
            expected_generation: 0,
            expected_state_version: 0,
        },
    };
    let Operation::Trigger(operation) = prepare(&command, &config()).unwrap() else {
        panic!("trigger")
    };
    let TriggerOperation::Apply(request) = *operation else {
        panic!("apply")
    };
    let mut trigger = request.trigger.unwrap();
    let target = trigger.target.as_ref().unwrap();
    assert_eq!(target.kind, proto::TriggerTargetKind::StaticWeb as i32);
    assert!(target.service.is_empty() && target.contract.is_empty() && target.function.is_empty());
    assert!(
        target.route.is_none()
            && target.revision.is_none()
            && target.deployment_generation.is_none()
    );
    trigger.generation = 1;
    assert_eq!(
        response::trigger(trigger, "tenant-a", Some("browser")).unwrap()["manifest"]["spec"]
            ["target"],
        value["spec"]["target"]
    );
}
