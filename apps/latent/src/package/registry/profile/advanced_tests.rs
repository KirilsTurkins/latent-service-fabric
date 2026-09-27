use super::*;
use clap::Parser;
use latent_oci::{HttpOciRegistry, RegistryActions, RegistryResolution};
use serde_json::{json, Value};
use tokio::time::Instant;

fn profile() -> Value {
    json!({
        "formatVersion": 2, "origin": "https://registry.example", "repository": "tenant/site",
        "addresses": [], "credentialFile": "credentials.json",
        "bearerChallenge": {
            "realm": "https://auth.example/token", "service": "registry.example",
            "identity": {"tenant": "tenant", "principal": "publisher", "credentialEpoch": 7},
            "actions": "pull-push", "addresses": []
        },
        "network": {"maximumRedirects": 1, "destinations": [
            {"origin": "https://registry.example", "addresses": {
                "networks": ["192.0.2.0/24"], "specialAddresses": ["192.0.2.10"]},
             "resolution": {"mode": "static", "addresses": ["192.0.2.10"]}, "contentPrefixes": []},
            {"origin": "https://auth.example", "addresses": {
                "networks": ["192.0.2.0/24"], "specialAddresses": ["192.0.2.20"]},
             "resolution": {"mode": "dns", "server": "127.0.0.1:53", "maximumTtlSeconds": 60},
             "contentPrefixes": []}
        ]}
    })
}

fn load_value(value: &Value, credentials: &str) -> Result<Configured, Failure> {
    let root = tempfile::tempdir().unwrap();
    let path = root.path().join("registry.json");
    std::fs::write(&path, serde_json::to_vec(value).unwrap()).unwrap();
    std::fs::write(root.path().join("credentials.json"), credentials).unwrap();
    let cli = Cli::try_parse_from(["latent", "node", "list"]).unwrap();
    load(&path, &cli, Duration::from_secs(9))
}

const CREDENTIALS: &str =
    r#"{"mode":"basic","username":"publisher","password":"private-test-secret"}"#;

#[test]
fn advanced_cli_profile_preserves_separate_authorities_identity_limits_and_network() {
    let configured = load_value(&profile(), CREDENTIALS).unwrap();
    assert_eq!(configured.reference.registry, "registry.example");
    assert_eq!(
        configured.config.limits.operation_timeout,
        Duration::from_secs(9)
    );
    assert_eq!(configured.config.limits.max_in_flight, 1);
    let RegistryCredentials::BearerChallenge {
        realm,
        service,
        identity,
        actions,
        addresses,
        ..
    } = &configured.config.credentials
    else {
        panic!("challenge not installed")
    };
    assert_eq!(realm, "https://auth.example/token");
    assert_eq!(service, "registry.example");
    assert_eq!(identity.credential_epoch, 7);
    assert_eq!(*actions, RegistryActions::PullPush);
    assert!(addresses.is_empty());
    assert!(!format!("{:?}", configured.config).contains("private-test-secret"));
    let network = configured.network.unwrap();
    assert_eq!(network.maximum_redirects, 1);
    assert!(matches!(
        network.destinations[1].resolution,
        RegistryResolution::Dns {
            maximum_ttl_seconds: 60,
            ..
        }
    ));
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .unwrap();
    runtime.block_on(async {
        let client = HttpOciRegistry::new_with_network(configured.config, network).unwrap();
        assert_eq!(client.usage().network.unwrap().destinations, 2);
        assert_eq!(client.usage().bearer.unwrap().credential_epoch, 7);
        client
            .shutdown(Instant::now() + Duration::from_secs(1))
            .await
            .unwrap();
    });
}

#[test]
fn advanced_cli_profile_rejects_closed_fields_version_mixing_and_excess_authority() {
    let baseline = profile();
    for (pointer, change) in [
        ("/formatVersion", json!(1)),
        ("/formatVersion", json!(3)),
        ("/allowInsecureLoopback", json!(true)),
        ("/addresses", json!(["192.0.2.10:443"])),
        ("/bearerChallenge/addresses", json!(["192.0.2.20:443"])),
        ("/bearerChallenge/identity/credentialEpoch", json!(0)),
        ("/bearerChallenge/identity/tenant", json!("other tenant")),
        ("/bearerChallenge/actions", json!("pull,push,delete")),
        (
            "/bearerChallenge/inlinePassword",
            json!("private-test-secret"),
        ),
        ("/network/maximumRedirects", json!(4)),
        ("/network/destinations/0/addresses/networks", json!([])),
        ("/network/destinations/0/addresses/extra", json!(true)),
        (
            "/network/destinations/1/resolution/maximumTtlSeconds",
            json!(301),
        ),
        (
            "/network/destinations/1/resolution/addresses",
            json!(["192.0.2.20"]),
        ),
        ("/network", Value::Null),
        ("/bearerChallenge", Value::Null),
    ] {
        let mut value = baseline.clone();
        let (parent, key) = pointer.rsplit_once('/').unwrap();
        value.pointer_mut(parent).unwrap()[key] = change;
        assert!(
            decode(&serde_json::to_vec(&value).unwrap()).is_err(),
            "{pointer}"
        );
    }
    for credentials in [r#"{"mode":"bearer","token":"private-test-secret"}"#, "{}"] {
        let failure = load_value(&baseline, credentials).err().unwrap();
        assert!(!format!("{failure:?}").contains("private-test-secret"));
    }
}

#[test]
fn advanced_cli_profile_constructor_denies_wrong_realms_roots_and_destinations() {
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .unwrap();
    runtime.block_on(async {
        for (pointer, change) in [
            (
                "/origin",
                json!("https://registry.example@unapproved.example"),
            ),
            (
                "/bearerChallenge/realm",
                json!("https://unapproved.example/token"),
            ),
            (
                "/bearerChallenge/realm",
                json!("https://auth.example/token?scope=other"),
            ),
            (
                "/network/destinations/0/resolution/addresses",
                json!(["192.0.2.11"]),
            ),
            (
                "/network/destinations/1/origin",
                json!("https://registry.example"),
            ),
            ("/network/destinations/1/contentPrefixes", json!(["/v2/"])),
            (
                "/network/destinations/1/resolution/server",
                json!("0.0.0.0:53"),
            ),
        ] {
            let mut value = profile();
            *value.pointer_mut(pointer).unwrap() = change;
            let configured = load_value(&value, CREDENTIALS).unwrap();
            assert!(
                HttpOciRegistry::new_with_network(configured.config, configured.network.unwrap())
                    .is_err(),
                "{pointer}"
            );
        }
        let mut configured = load_value(&profile(), CREDENTIALS).unwrap();
        configured
            .config
            .additional_root_certificates
            .push(b"not a certificate".to_vec());
        assert!(
            HttpOciRegistry::new_with_network(configured.config, configured.network.unwrap())
                .is_err()
        );
    });
}
