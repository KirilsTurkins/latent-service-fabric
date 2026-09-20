use super::*;
use crate::{
    args::Cli,
    config::InputLimits,
    management::phase2::projection::{self, Project},
};
use clap::Parser;
use std::time::Duration;

fn manifest() -> Value {
    json!({"apiVersion":"latent.dev/v1alpha1","kind":"HttpTrigger",
        "metadata":{"name":"browser","tenant":"tenant-a"},
        "spec":{"target":{"service":"tenant-a/browser","contract":"latent:web/application@0.1.0",
            "function":"handle","route":"web","publication":format!("publication:sha256:{}","a".repeat(64)),
            "revision":format!("revision-v1:sha256:{}","b".repeat(64)),"deploymentGeneration":1},
            "configuration":{"profile":"buffered-v1","scheme":"https","host":"EXAMPLE.TEST:443",
                "path":"/api/%7euser","pathMatch":"exact","method":"GET"}}})
}

fn config() -> ResolvedConfig {
    ResolvedConfig {
        endpoint: "http://127.0.0.1:1".into(),
        tenant: "tenant-a".into(),
        token: "test-only".into(),
        connect_timeout: Duration::from_secs(1),
        rpc_timeout: Duration::from_secs(1),
        limits: InputLimits::default(),
    }
}

#[test]
fn explicit_trigger_grammar_rejects_missing_preconditions_and_unimplemented_profiles() {
    for arguments in [
        vec!["latent", "trigger", "apply", "trigger.json"],
        vec![
            "latent",
            "trigger",
            "delete",
            "web",
            "--operation-id",
            "delete",
            "--expected-generation",
            "1",
        ],
        vec!["latent", "trigger", "list", "--page-size", "33"],
        vec!["latent", "trigger", "watch"],
        vec![
            "latent",
            "trigger",
            "get",
            "web",
            "--actor",
            "administrator",
        ],
    ] {
        assert!(Cli::try_parse_from(arguments).is_err());
    }
    let parsed = Cli::try_parse_from([
        "latent",
        "trigger",
        "apply",
        "trigger.json",
        "--operation-id",
        "create",
        "--expected-generation",
        "0",
        "--expected-state-version",
        "9007199254740993",
    ])
    .unwrap();
    parsed.validate().unwrap();
}

#[test]
fn preparation_is_local_and_canonical_without_component_substitution() {
    let directory = tempfile::tempdir().unwrap();
    let file = directory.path().join("trigger.json");
    std::fs::write(&file, serde_json::to_vec(&manifest()).unwrap()).unwrap();
    let command = TriggerCommand::Apply {
        file: file.clone(),
        mutation: TriggerMutation {
            operation_id: "create".into(),
            expected_generation: 0,
            expected_state_version: 9_007_199_254_740_993,
        },
    };
    let Operation::Trigger(operation) = prepare(&command, &config()).unwrap() else {
        panic!("trigger operation")
    };
    assert_eq!(
        operation.recovery().unwrap()["expectedStateVersion"],
        "9007199254740993"
    );
    let TriggerOperation::Apply(request) = *operation else {
        panic!("apply request")
    };
    let trigger = request.trigger.unwrap();
    assert_eq!(trigger.configuration["host"], "example.test");
    assert_eq!(trigger.configuration["path"], "/api/~user");
    assert_eq!(
        trigger
            .target
            .as_ref()
            .unwrap()
            .publication
            .as_ref()
            .unwrap()
            .tenant,
        "tenant-a"
    );
    assert_eq!(
        trigger
            .target
            .as_ref()
            .unwrap()
            .publication
            .as_ref()
            .unwrap()
            .id,
        format!("publication:sha256:{}", "a".repeat(64))
    );
    assert_eq!(trigger.generation, 0);
    for change in ["tenant", "publication", "profile", "credential"] {
        let mut value = manifest();
        match change {
            "tenant" => value["metadata"]["tenant"] = json!("tenant-b"),
            "publication" => {
                value["spec"]["target"]["publication"] =
                    json!(format!("sha256:{}", "a".repeat(64)));
            }
            "profile" => value["spec"]["configuration"]["profile"] = json!("future"),
            "credential" => value["spec"]["configuration"]["token"] = json!("must-not-be-accepted"),
            _ => unreachable!(),
        }
        std::fs::write(&file, serde_json::to_vec(&value).unwrap()).unwrap();
        assert!(prepare(&command, &config()).is_err(), "{change}");
    }
}

fn receipt() -> proto::TriggerOperationReceipt {
    let digest = format!("sha256:{}", "a".repeat(64));
    proto::TriggerOperationReceipt {
        format_version: 1,
        tenant: "tenant-a".into(),
        actor: Some(proto::ReleaseActor {
            subject: "operator".into(),
            kind: proto::ReleaseActorKind::User as i32,
        }),
        operation_id: "create".into(),
        action: proto::TriggerOperationAction::Apply as i32,
        trigger_id: "web".into(),
        request_digest: digest.clone(),
        expected_state_version: 10,
        expected_generation: 0,
        object_generation: 11,
        state_version: 11,
        route_generation: 2,
        manifest_digest: digest.clone(),
        publication: Some(proto::PublicationRef {
            id: format!("publication:{digest}"),
            tenant: "tenant-a".into(),
        }),
        component_digest: digest.clone(),
        deployment_id: "web-deployment".into(),
        deployment_generation: 1,
        revision: format!("revision-v1:{digest}"),
        completed_at_unix_millis: u64::MAX,
        receipt_digest: digest,
    }
}

#[test]
fn receipts_bind_scope_publication_and_counters_without_rounding() {
    let original = receipt();
    response::receipt_scope(&original, "tenant-a", "create", Some("web")).unwrap();
    assert_eq!(
        original.clone().project()["completedAtUnixMillis"],
        u64::MAX.to_string()
    );
    assert!(response::receipt_scope(&original, "tenant-b", "create", None).is_err());
    assert!(response::receipt_scope(&original, "tenant-a", "other", None).is_err());
    for mutate in [
        (|value: &mut proto::TriggerOperationReceipt| {
            value.publication.as_mut().unwrap().tenant = "tenant-b".into();
        }) as fn(&mut proto::TriggerOperationReceipt),
        |value| value.publication.as_mut().unwrap().id = value.component_digest.clone(),
        |value| value.actor = None,
        |value| value.action = 999,
        |value| value.state_version = value.expected_state_version,
        |value| value.expected_generation = u64::MAX,
        |value| value.object_generation = 1,
        |value| value.route_generation = value.state_version + 1,
        |value| value.deployment_generation = value.route_generation + 1,
    ] {
        let mut value = original.clone();
        mutate(&mut value);
        assert!(projection::checked(&value, 4096).is_err());
    }
}

#[test]
fn apply_and_delete_receipts_retain_catalog_assigned_object_generations() {
    for (action, expected, object) in [
        (proto::TriggerOperationAction::Apply, 0, 11),
        (proto::TriggerOperationAction::Apply, 7, 11),
        (proto::TriggerOperationAction::Delete, 7, 7),
        (proto::TriggerOperationAction::Delete, 10, 10),
    ] {
        let mut value = receipt();
        value.action = action as i32;
        value.expected_generation = expected;
        value.object_generation = object;
        let decoded = <proto::TriggerOperationReceipt as prost::Message>::decode(
            prost::Message::encode_to_vec(&value).as_slice(),
        )
        .unwrap();
        response::receipt_scope(&decoded, "tenant-a", "create", Some("web")).unwrap();
        assert_eq!(decoded.project()["objectGeneration"], object.to_string());
    }
    for (action, expected, object) in [
        (proto::TriggerOperationAction::Apply, 0, 1),
        (proto::TriggerOperationAction::Apply, 11, 11),
        (proto::TriggerOperationAction::Delete, 7, 8),
        (proto::TriggerOperationAction::Delete, 0, 0),
        (proto::TriggerOperationAction::Delete, 11, 11),
    ] {
        let mut value = receipt();
        value.action = action as i32;
        value.expected_generation = expected;
        value.object_generation = object;
        assert!(projection::checked(&value, 4096).is_err());
    }
}

#[test]
fn deletion_retains_uncertainty_and_rejects_misattributed_or_noncanonical_metadata() {
    let mut metadata = tonic::metadata::MetadataMap::new();
    metadata.insert_bin(
        "latent-trigger-operation-bin",
        tonic::metadata::MetadataValue::from_bytes(b"delete"),
    );
    for (key, value) in [
        ("latent-trigger-state", "3"),
        ("latent-trigger-generation", "2"),
        ("latent-trigger-replayed", "true"),
        ("latent-trigger-durability", "uncertain"),
    ] {
        metadata.insert(key, value.parse().unwrap());
    }
    metadata.insert(
        "latent-trigger-receipt",
        format!("sha256:{}", "a".repeat(64)).parse().unwrap(),
    );
    let operation = proto::TriggerOperationPrecondition {
        operation_id: "delete".into(),
        expected_state_version: Some(2),
    };
    let value = response::deletion(&metadata, &operation, 2, "web").unwrap();
    assert_eq!(value["durability"], "uncertain");
    assert_eq!(value["replayed"], true);
    assert_eq!(value["generation"], "2");
    assert!(response::deletion(&metadata, &operation, 1, "web").is_err());
    assert!(response::deletion(&metadata, &operation, 0, "web").is_err());
    metadata.insert("latent-trigger-state", "03".parse().unwrap());
    assert!(response::deletion(&metadata, &operation, 2, "web").is_err());
    metadata.insert("latent-trigger-state", "3".parse().unwrap());
    metadata.insert_bin(
        "latent-trigger-operation-bin",
        tonic::metadata::MetadataValue::from_bytes(b"other"),
    );
    assert!(response::deletion(&metadata, &operation, 2, "web").is_err());
}
