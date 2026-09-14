//! Actual guest calls and original capability authority through Vault KV-v2.
#![cfg(all(target_os = "linux", target_arch = "x86_64"))]
#[path = "vault_secrets/audit.rs"]
mod audit;
#[path = "vault_secrets/bounds.rs"]
mod bounds;
#[path = "local_secrets/component.rs"]
mod component;
#[path = "local_secrets/fixture.rs"]
#[allow(dead_code)]
mod fixture;
#[path = "local_secrets/packages.rs"]
mod packages;
#[path = "vault_secrets/server.rs"]
mod server;
#[path = "vault_secrets/setup.rs"]
mod setup;
#[path = "generic_backend/support.rs"]
#[allow(dead_code)]
mod support;
#[path = "vault_secrets/transport.rs"]
mod transport;
use fixture::*;
use latent_capabilities::broker::secrets::{SecretError, SecretInvoker};
use latent_secrets::vault::VaultSecretProvider;

fn marker(first: u8, version: u8, length: u64) -> u64 {
    (u64::from(first) << 32) | (u64::from(version) << 16) | length
}
async fn invoke(f: &Fixture<VaultSecretProvider>, mode: u32) -> u64 {
    let (request, control) = f.request("same-public-activation-id", mode);
    let report = f.backend.invoke_contained(request, &control).await;
    let GuestOutcome::Returned {
        output,
        consumption,
        ..
    } = report.outcome.unwrap()
    else {
        panic!("Vault guest result")
    };
    assert_eq!(report.cleanup, ExecutionCleanup::Reusable);
    assert!(control
        .budget
        .finalize_at(Some(&consumption), Instant::now())
        .violation()
        .is_none());
    setup::idle(f).await;
    serde_json::from_slice::<Vec<String>>(&output).unwrap()[0]
        .parse()
        .unwrap()
}
async fn shutdown(f: &Fixture<VaultSecretProvider>) {
    f.provider.close();
    f.secrets.close();
    assert!(f
        .pools
        .shutdown(Instant::now() + Duration::from_secs(2))
        .await
        .unwrap()
        .is_clean());
    assert_eq!(f.provider.snapshot().unwrap().retained_plaintext_bytes, 0);
}

#[tokio::test]
#[ignore = "requires tools/run_vault_secret_tests.py owned pinned TLS Vault"]
async fn real_vault_versions_rotation_revocation_and_guest_cleanup() {
    setup::control("reset-fixture");
    let config = setup::configured();
    let f = setup::fixture(config.clone(), None).await;
    assert_eq!(invoke(&f, 0).await, marker(b'A', b'1', 5));
    assert_eq!(invoke(&f, 0).await, marker(b'A', b'1', 5));
    assert_eq!(f.provider.snapshot().unwrap().remote_read_attempts, 1);
    assert_eq!(f.provider.snapshot().unwrap().cache_hits, 1);
    assert_eq!(invoke(&f, 1).await, 1001); // Not granted; no remote call.
    assert_eq!(invoke(&f, 3).await, 1000); // Same spelling belongs to another tenant.
    assert_eq!(invoke(&f, 4).await, 1002); // Explicit operator expiry.
    setup::control("write-beta");
    assert_eq!(invoke(&f, 0).await, marker(b'A', b'1', 5)); // Explicit bounded freshness.
    setup::expire(&f);
    assert_eq!(invoke(&f, 0).await, marker(b'B', b'2', 4));
    assert_eq!(invoke(&f, 2).await, marker(b'A', b'1', 5)); // Exact version one.
    setup::control("delete-latest");
    setup::expire(&f);
    assert_eq!(invoke(&f, 0).await, 1000);
    setup::control("restore-latest");
    assert_eq!(invoke(&f, 0).await, marker(b'B', b'2', 4));
    setup::control("destroy-first");
    setup::expire(&f);
    assert_eq!(invoke(&f, 2).await, 1000);
    let (session, _) = f.session("rotation-before-disclosure");
    let held = f
        .provider
        .read(&session, "allowed".into())
        .unwrap()
        .await
        .unwrap();
    setup::rotate(&f, &config, setup::SECOND_TOKEN).await;
    let mut copied = false;
    assert!(matches!(
        held.disclose(&mut |_| copied = true),
        Err(SecretError::Unavailable)
    ));
    assert!(!copied);
    drop(session);
    assert_eq!(invoke(&f, 0).await, marker(b'B', b'2', 4));
    setup::control("revoke-second");
    setup::expire(&f);
    assert_eq!(invoke(&f, 0).await, 1001);
    setup::rotate(&f, &config, setup::FIRST_TOKEN).await;
    assert_eq!(invoke(&f, 0).await, marker(b'B', b'2', 4));
    let before = f.provider.snapshot().unwrap();
    f.dormant_deployments().await;
    assert_eq!(f.provider.snapshot().unwrap(), before);
    shutdown(&f).await;
}
