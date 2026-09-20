use super::*;
use latent_secrets::{LocalSecretStore, SecretLimits, SystemSecretClock};

#[tokio::test]
async fn explicit_open_deadline_and_unpolled_drop_preserve_existing_credentials() {
    let fixture = Fixture::new().await;
    let expired = LocalSecretStore::open_before(
        fixture.pools.clone(),
        fixture.directory.path().join("secrets"),
        SecretLimits::default(),
        Vec::new(),
        Arc::new(SystemSecretClock),
        Instant::now(),
    )
    .unwrap();
    assert!(matches!(expired.await, Err(SecretError::Unavailable)));
    let abandoned = LocalSecretStore::open_before(
        fixture.pools.clone(),
        fixture.directory.path().join("secrets"),
        SecretLimits::default(),
        Vec::new(),
        Arc::new(SystemSecretClock),
        Instant::now() + Duration::from_secs(1),
    )
    .unwrap();
    drop(abandoned);
    assert_eq!(invoke(&fixture, 0).await, marker(b'A', b'1', 5));
    shutdown(&fixture).await;
}

#[tokio::test]
async fn expired_or_abandoned_reload_reclaims_candidate_without_generation_change() {
    let fixture = Fixture::new().await;
    let original = fixture.secrets.snapshot().unwrap();
    let expired = fixture
        .secrets
        .reload_before(1, specs("2"), Instant::now())
        .unwrap();
    assert!(fixture.secrets.snapshot().unwrap().loading);
    assert!(matches!(expired.await, Err(SecretError::Unavailable)));
    let abandoned = fixture
        .secrets
        .reload_before(1, specs("2"), Instant::now() + Duration::from_secs(1))
        .unwrap();
    drop(abandoned);
    let retained = fixture.secrets.snapshot().unwrap();
    assert_eq!(retained.generation, original.generation);
    assert_eq!(retained.retained_generations, original.retained_generations);
    assert_eq!(
        retained.reserved_generation_bytes,
        original.reserved_generation_bytes
    );
    assert!(!retained.loading);
    assert_eq!(invoke(&fixture, 0).await, marker(b'A', b'1', 5));
    assert_eq!(
        fixture
            .secrets
            .reload_before(1, specs("2"), Instant::now() + Duration::from_secs(1))
            .unwrap()
            .await
            .unwrap(),
        2
    );
    assert_eq!(invoke(&fixture, 0).await, marker(b'A', b'2', 5));
    shutdown(&fixture).await;
}
