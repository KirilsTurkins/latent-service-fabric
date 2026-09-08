use std::fs;

use latent_core::{PlatformError, PrincipalKind, TenantId};
use latent_scheduler::CellClass;
use tempfile::TempDir;

use super::{input, CellConfig, CredentialRole, NodeConfig, NodeSettings, MIB};

const TOKEN: &str = "example-local-token-replace-with-32-random-bytes";

fn document() -> String {
    format!(
        r#"{{"formatVersion":1,"dataDirectory":"data","nodeId":"node-one","credentials":[{{"token":"{TOKEN}","subject":"operator","tenant":"examples","role":"operator"}}]}}"#
    )
}

fn config() -> (TempDir, NodeConfig) {
    let directory = TempDir::new().expect("temporary configuration directory");
    let path = directory.path().join("node.json");
    fs::write(&path, document()).expect("write configuration");
    let config = NodeConfig::load(&path).expect("load configuration");
    (directory, config)
}

fn failure(result: Result<NodeSettings, PlatformError>) -> PlatformError {
    match result {
        Err(error) => error,
        Ok(_) => panic!("invalid configuration was accepted"),
    }
}

#[test]
fn defaults_derive_compatible_node_limits_without_creating_storage() {
    let (directory, config) = config();
    let settings = config.derive().expect("derive standalone defaults");
    assert_eq!(settings.runtime_workers(), 2);
    assert_eq!(settings.control_workers(), 2);
    assert_eq!(settings.shutdown_grace(), std::time::Duration::from_secs(1));
    assert!(settings.data_directory.is_absolute());
    assert!(!directory.path().join("data").exists());
    assert_eq!(
        settings.scheduler.queue_capacity_per_class[&CellClass::Standard],
        16
    );
    assert_eq!(settings.admission.cell_classes["standard"].parallelism, 2);
    assert_eq!(settings.admission.limits.maximum_concurrent_activations, 18);
    assert_eq!(settings.admission.limits.maximum_queued_activations, 18);
    assert_eq!(settings.manager.journal.maximum_active, 18);
    assert_eq!(settings.wasmtime.maximum_active_instances, 2);
    assert_eq!(settings.inventory.cell_classes, [CellClass::Standard]);
    assert_eq!(
        settings.wasmtime.maximum_component_bytes,
        settings.artifacts.max_component_bytes
    );
    assert_eq!(
        settings.management.max_component_bytes,
        settings.artifacts.max_component_bytes
    );
    assert_eq!(
        settings.invocation.max_cancel_reason_bytes,
        settings.manager.maximum_cancellation_reason_bytes
    );
    assert_eq!(settings.management.auth, settings.invocation);
    assert!(
        settings.management.max_page_token_bytes
            >= 64 + 6 * settings.deployments.max_identifier_bytes
    );
    assert_eq!(settings.inventory.maximum_load_age, super::LOAD_MAXIMUM_AGE);
    assert!(settings.load_sample_interval < settings.inventory.maximum_load_age);
    let quotas = latent_admission::LocalQuotaProvider::new(settings.admission)
        .expect("derived admission policy is valid");
    latent_scheduler::LocalScheduler::new(settings.scheduler, quotas)
        .expect("derived class and queue policies compose");
    latent_telemetry::StructuredLocalSink::new(settings.local_sink)
        .expect("derived local capture bounds are valid");
}

#[test]
fn credentials_derive_exact_scoped_principals_and_secure_exposure() {
    let (_directory, mut config) = config();
    config.credentials[0].role = CredentialRole::Invoke;
    let mut administrator = config.credentials[0].clone();
    administrator.token = "other-distinct-token-with-at-least-32-bytes".to_owned();
    administrator.subject = "administrator".to_owned();
    administrator.role = CredentialRole::Admin;
    config.credentials.push(administrator);
    let settings = config.derive().expect("derive roles");
    let credentials = &settings.transport.credentials;
    assert_eq!(credentials[0].principal.kind, PrincipalKind::User);
    assert_eq!(credentials[1].principal.kind, PrincipalKind::Administrator);
    assert!(credentials
        .iter()
        .all(|credential| credential.principal.claims.is_empty()));
    let tenant = &settings.admission.tenants[&TenantId("examples".to_owned())];
    assert_eq!(tenant.allowed_subjects.len(), 2);
    assert!(!tenant.allowed_subjects.contains("foreign"));
    assert_eq!(
        settings.wasmtime.context_policy.metadata_prefixes,
        ["guest."]
    );
    assert!(settings.wasmtime.context_policy.claim_keys.is_empty());
    assert!(settings.wasmtime.context_policy.baggage_keys.is_empty());
    assert!(!settings.observer.export_guest_log_bodies);
    assert!(settings.observer.allowed_guest_field_names.is_empty());
    config.credentials[0].role = CredentialRole::Operator;
    let settings = config.derive().expect("derive operator role");
    let principal = &settings.transport.credentials[0].principal;
    assert_eq!(principal.tenant, Some(TenantId("examples".to_owned())));
    assert_eq!(principal.claims["latent.node.operator"], "true");
}

#[test]
fn malformed_json_never_echoes_secret_values() {
    let raw = document();
    for source in [
        raw.replace(
            "\"formatVersion\":1",
            "\"formatVersion\":1,\"formatVersion\":1",
        ),
        raw.replace(
            "\"role\":\"operator\"",
            "\"role\":\"operator\",\"role\":\"admin\"",
        ),
        raw.replace(
            "\"subject\":\"operator\"",
            "\"unexpectedSecret\":\"sensitive\",\"subject\":\"operator\"",
        ),
        raw.replace("\"formatVersion\":1", "\"formatVersion\":2.5"),
    ] {
        let error = input::decode(source.as_bytes())
            .err()
            .expect("reject invalid JSON");
        assert!(!error.message.contains(TOKEN));
        assert!(!error.message.contains("sensitive"));
        assert!(error.details.is_empty());
    }
}

#[test]
fn document_size_and_nesting_are_bounded_before_deserialization() {
    for bytes in [vec![b' '; 64 * 1024 + 1], vec![b'['; 17]] {
        assert!(input::decode(&bytes).is_err());
    }
    let raw = document().replace("node-one", "node-{[\\\"quoted\\\"]}");
    assert!(
        input::decode(raw.as_bytes()).is_ok(),
        "braces in strings are not nesting"
    );
}

#[test]
fn relative_paths_anchor_to_configuration_parent_and_port_zero_is_valid() {
    let (directory, mut config) = config();
    assert_eq!(
        config.data_directory,
        directory
            .path()
            .canonicalize()
            .expect("parent")
            .join("data")
    );
    config.bind.set_port(0);
    assert_eq!(
        config
            .derive()
            .expect("ephemeral loopback bind")
            .transport
            .bind
            .port(),
        0
    );
    config.data_directory = "relative-again".into();
    assert!(
        config.derive().is_err(),
        "direct derive cannot defer cwd anchoring"
    );
}

#[test]
fn invalid_capacity_and_retention_combinations_fail_before_startup() {
    let (_directory, config) = config();
    let mutations: [fn(&mut NodeConfig); 8] = [
        |value| value.cells[0].queue_capacity = 0,
        |value| value.cells[0].capacity = 0,
        |value| value.cache.source_bytes = value.limits.maximum_component_bytes - 1,
        |value| value.retention.bytes = MIB,
        |value| value.workers.control = 0,
        |value| value.catalogs.release_entries = usize::MAX,
        |value| value.execution.maximum_cpu_fuel = u64::MAX,
        |value| value.cache.preparations = 3,
    ];
    for mutate in mutations {
        let mut invalid = config.clone();
        mutate(&mut invalid);
        let error = failure(invalid.derive());
        assert!(!error.message.contains(TOKEN));
    }
    let mut invalid = config;
    invalid.cells.push(CellConfig {
        class: "large".to_owned(),
        capacity: 1,
        queue_capacity: 1,
        maximum_memory_bytes: MIB as u64,
    });
    assert!(
        invalid.derive().is_err(),
        "larger classes cannot have smaller memory ceilings"
    );
}

#[test]
fn nonlocal_bind_duplicate_tokens_and_unusable_manifest_tenants_are_rejected() {
    let (_directory, config) = config();
    let mutations: [fn(&mut NodeConfig); 6] = [
        |value| value.bind = "0.0.0.0:50051".parse().expect("address"),
        |value| value.credentials.clear(),
        |value| value.credentials.push(value.credentials[0].clone()),
        |value| value.credentials[0].tenant = "-invalid".to_owned(),
        |value| value.credentials[0].tenant = "a".repeat(129),
        |value| value.credentials[0].token = "short".to_owned(),
    ];
    for mutate in mutations {
        let mut invalid = config.clone();
        mutate(&mut invalid);
        assert!(invalid.derive().is_err());
    }
}

#[test]
fn zero_log_budget_preserves_exact_denial_across_rpc_and_admission() {
    let (_directory, mut config) = config();
    config.execution.maximum_log_bytes = 0;
    let settings = config
        .derive()
        .expect("zero logging is an explicit grant denial");
    assert_eq!(settings.invocation.max_log_bytes, 0);
    assert_eq!(settings.admission.budget_ceiling.log_bytes, 0);
    assert!(settings.wasmtime.invocation_log_maximum_bytes > 0);
}
