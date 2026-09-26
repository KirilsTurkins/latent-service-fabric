use super::*;
use latent_secrets::{LocalSecretStore, SecretLimits};

#[tokio::test]
async fn invalid_sources_counts_and_capacity_preserve_the_current_generation() {
    let f = Fixture::new().await;
    let mut duplicate = specs("2");
    duplicate.extend(specs("2"));
    assert!(f.secrets.reload(1, duplicate).is_err());
    let mut huge_capacity = Vec::with_capacity(17);
    huge_capacity.extend(specs("2"));
    assert!(f.secrets.reload(1, huge_capacity).is_err());
    let root = f.directory.path().join("secrets");
    write(&root.join("value"), &vec![42; 16385]);
    assert!(f.secrets.reload(1, specs("2")).unwrap().await.is_err());
    assert_eq!(invoke(&f, 0).await, marker(b'A', b'1', 5));
    write(&root.join("value"), b"Alpha");
    let store = LocalSecretStore::open(
        f.pools.clone(),
        root,
        SecretLimits {
            maximum_generation_bytes: 8,
            maximum_value_bytes: 8,
            ..SecretLimits::default()
        },
        vec![],
        f.secret_clock.clone(),
    )
    .unwrap()
    .await
    .unwrap();
    // Four individually valid values exceed the retained capacity together.
    assert!(store.reload(0, specs("1")).unwrap().await.is_err());
    assert_eq!(store.snapshot().unwrap().retained_generations, 0);
    assert_eq!(store.snapshot().unwrap().generation, 0);
    store.close();
    shutdown(&f).await;
}
