use super::*;
use latent_core::{DeploymentId, ReleaseDigest, RevisionId, RouteGeneration};

fn static_attempt() -> AuditOperationAttempt {
    let mut value = attempt();
    value.action = AuditControlAction::TriggerApply;
    value.expected_state_version = Some(0);
    value.identities = AuditIdentities {
        trigger: Some("static-site".into()),
        trigger_generation: Some(1),
        publication: Some(
            format!("publication:sha256:{}", "a".repeat(64))
                .parse()
                .unwrap(),
        ),
        static_web: Some(AuditStaticWebTarget {
            web_manifest_digest: digest(),
            assets_digest: digest(),
            web_generation: 1,
        }),
        // Static-only nodes have no application route generation to advance.
        route_generation: Some(RouteGeneration(0)),
        state_version: Some(1),
        ..AuditIdentities::default()
    };
    value
}

#[test]
fn static_trigger_commit_and_legacy_application_records_survive_restart() {
    let directory = Directory::new();
    let path = directory.0.join("static-audit");
    let value = static_attempt();
    let mut legacy = value.clone();
    legacy.operation_id = "application".into();
    legacy.identities.static_web = None;
    legacy.identities.route_generation = Some(RouteGeneration(1));
    legacy.identities.component = Some(ReleaseDigest(digest().to_string()));
    legacy.identities.deployment = Some(DeploymentId("app".into()));
    legacy.identities.deployment_generation = Some(1);
    legacy.expected_deployment_generation = Some(1);
    legacy.identities.revision = Some(RevisionId("revision-v1:one".into()));
    let bytes = codec::encode(&legacy, 4096).unwrap();
    assert!(!std::str::from_utf8(&bytes).unwrap().contains("staticWeb"));
    assert_eq!(
        codec::decode::<AuditOperationAttempt>(&bytes, 4096).unwrap(),
        legacy
    );
    let (handle, mut worker) = open(&path, AuditLimits::default()).unwrap();
    for expected in [&value, &legacy] {
        let mut done = conclusion();
        done.identities = expected.identities.clone();
        handle.preflight_conclusion(expected, &done).unwrap();
        let mut guard = handle
            .reserve_control_critical(expected)
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
    let page = admitted_query(&handle, &query(value.scope.clone()))
        .unwrap()
        .blocking_wait()
        .unwrap();
    assert_eq!(page.records().len(), 4);
    let AuditRecordData::Outcome { conclusion, .. } = &page.records()[1].data else {
        panic!("outcome")
    };
    assert_eq!(conclusion.identities, value.identities);
    assert_eq!(conclusion.result, AuditOperationResult::Committed);
    assert!(conclusion.identities.component.is_none());
    drop(page);
    stop(&handle, &mut worker);
}

#[test]
fn static_trigger_audit_rejects_hybrids_missing_scope_and_incomplete_identity() {
    let valid = static_attempt();
    codec::attempt(&valid).unwrap();
    for case in 0..12 {
        let mut value = valid.clone();
        match case {
            0 => value.identities.component = Some(ReleaseDigest(digest().to_string())),
            1 => value.identities.deployment = Some(DeploymentId("app".into())),
            2 => value.identities.deployment_generation = Some(1),
            3 => value.identities.revision = Some(RevisionId("app".into())),
            4 => value.identities.static_web.as_mut().unwrap().web_generation = 0,
            5 => value.identities.publication = None,
            6 => value.identities.trigger = None,
            7 => value.identities.static_web = None,
            8 => value.expected_deployment_generation = Some(1),
            9 => value.scope = AuditScope::Node,
            10 => value.identities.route_generation = None,
            _ => value.action = AuditControlAction::Publish,
        }
        assert!(codec::attempt(&value).is_err(), "{case}");
    }
    for field in ["staticWeb", "webManifestDigest", "assetsDigest"] {
        let mut json = serde_json::to_value(&valid).unwrap();
        if field == "staticWeb" {
            json["identities"][field] = serde_json::Value::Null;
        } else {
            json["identities"]["staticWeb"][field] = "invalid".into();
        }
        assert!(serde_json::from_value::<AuditOperationAttempt>(json).is_err());
    }
}
