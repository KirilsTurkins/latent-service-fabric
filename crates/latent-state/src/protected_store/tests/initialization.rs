use super::*;

fn fresh(owner: &ProtectedStoreOwner) -> bool {
    wait(
        owner
            .with_initializing_store(1024, |engine, witness| {
                assert!(engine.snapshot()?.is_empty()?);
                Ok(witness.is_some_and(|witness| witness.matches_store(engine)))
            })
            .unwrap(),
    )
    .unwrap()
    .unwrap()
}

#[test]
fn fresh_initialization_witness_is_affine_and_does_not_survive_reopening() {
    let (_root, config) = fixture();
    let owner = start(config.clone());
    assert!(fresh(&owner));
    assert!(!fresh(&owner));
    assert!(finish(&owner).snapshot.physically_retired());
    owner.reap_retired_threads().unwrap();
    let reopened = start(config);
    assert!(!fresh(&reopened));
    assert!(finish(&reopened).snapshot.physically_retired());
    reopened.reap_retired_threads().unwrap();
}

#[test]
fn reopened_anchors_and_retained_family_rows_never_mint_fresh_initialization() {
    for changed in 0..3 {
        let (root, config) = fixture();
        if changed == 0 {
            OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(root.path().join(&config.file_name))
                .unwrap();
            fs::set_permissions(
                root.path().join(&config.file_name),
                fs::Permissions::from_mode(0o600),
            )
            .unwrap();
        }
        let owner = start(config.clone());
        if changed == 1 {
            wait(
                owner
                    .apply(batch(b"retained-state-command-and-outbox"))
                    .unwrap(),
            )
            .unwrap()
            .unwrap();
        }
        if changed < 2 {
            assert!(!wait(
                owner
                    .with_initializing_store(1024, |_, proof| Ok(proof.is_some()))
                    .unwrap()
            )
            .unwrap()
            .unwrap());
        }
        assert!(finish(&owner).snapshot.physically_retired());
        owner.reap_retired_threads().unwrap();
        if changed == 2 {
            // The original retired fixture lock remains. A lost engine leaf is
            // never a second wholly new protected owner, even if creation is on.
            fs::remove_file(root.path().join(&config.file_name)).unwrap();
            let reopened = start(config);
            assert!(!fresh(&reopened));
            assert!(finish(&reopened).snapshot.physically_retired());
            reopened.reap_retired_threads().unwrap();
        }
    }
}
