use super::*;
use latent_capabilities::broker::secrets::CredentialScope;
use latent_secrets::{LocalSecretStore, SecretLimits, SecretSource};

#[test]
fn bounded_initial_environment_capture_uses_only_allowlisted_names() {
    let status = std::process::Command::new(std::env::current_exe().unwrap())
        .args([
            "--exact",
            "environment::initial_environment_child",
            "--nocapture",
        ])
        .env("LSF_SECRET_TEST_CHILD_215", "yes")
        .env(
            "LSF_SECRET_TEST_VALUE_215",
            "synthetic-environment-secret-215",
        )
        .env("LSF_SECRET_TEST_DENIED_215", "must-not-be-selected")
        .status()
        .unwrap();
    assert!(status.success());
}
#[test]
fn initial_environment_child() {
    if std::env::var("LSF_SECRET_TEST_CHILD_215").as_deref() != Ok("yes") {
        return;
    }
    tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .unwrap()
        .block_on(async {
            let f = Fixture::new().await;
            let store = LocalSecretStore::open(
                f.pools.clone(),
                f.directory.path().join("secrets"),
                SecretLimits::default(),
                vec!["LSF_SECRET_TEST_VALUE_215".into()],
                f.secret_clock.clone(),
            )
            .unwrap()
            .await
            .unwrap();
            let mut values = specs("1");
            values[1].source = SecretSource::Environment {
                key: "LSF_SECRET_TEST_VALUE_215".into(),
            };
            store.reload(0, values).unwrap().await.unwrap();
            let binding = store
                .bind_credential(
                    CredentialScope {
                        tenant: TenantId("tests".into()),
                        provider_id: "http".into(),
                        origin: latent_policy::capability::HttpOrigin {
                            scheme: "http".into(),
                            host: "127.0.0.1".into(),
                            port: 8080,
                        },
                    },
                    "opaque".into(),
                )
                .unwrap();
            binding
                .with_current_value(&mut |value| {
                    assert_eq!(value, b"synthetic-environment-secret-215");
                    Ok(())
                })
                .unwrap();
            let mut denied = specs("2");
            denied[0].source = SecretSource::Environment {
                key: "LSF_SECRET_TEST_DENIED_215".into(),
            };
            assert!(matches!(
                store.reload(1, denied),
                Err(SecretError::PermissionDenied)
            ));
            assert_eq!(store.snapshot().unwrap().generation, 1);
            let tiny = LocalSecretStore::open(
                f.pools.clone(),
                f.directory.path().join("secrets"),
                SecretLimits {
                    maximum_environment_bytes: 1,
                    ..SecretLimits::default()
                },
                vec!["LSF_SECRET_TEST_VALUE_215".into()],
                f.secret_clock.clone(),
            )
            .unwrap()
            .await
            .unwrap();
            let mut values = specs("1");
            values[0].source = SecretSource::Environment {
                key: "LSF_SECRET_TEST_VALUE_215".into(),
            };
            assert!(tiny.reload(0, values).unwrap().await.is_err());
            assert_eq!(tiny.snapshot().unwrap().generation, 0);
            store.close();
            tiny.close();
            drop(binding);
            shutdown(&f).await;
        });
}
