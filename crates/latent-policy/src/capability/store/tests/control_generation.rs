use super::*;

#[test]
fn control_generation_comes_from_complete_persisted_image_and_rejects_foreign_reopen() {
    let fixture = Fixture::new();
    let store = fixture.store(PolicyStoreLimits::default());
    let bytes = serde_json::to_vec(&policy()).unwrap();
    mutate(&store, "p", "create", 0, Some(&bytes)).unwrap();
    mutate(&store, "other", "other-create", 0, Some(&bytes)).unwrap();
    let captured = store.capture_control_generation(deadline()).unwrap();
    let generation = store.lock().unwrap().image.generation;
    assert_eq!(captured.persisted_generation(), generation);
    assert!(generation > store.lock().unwrap().image.records[0].revision);
    let mut observed = None;
    store
        .with_control_generation(&captured, deadline(), &mut |actual| {
            observed = Some(actual);
            Ok(())
        })
        .unwrap();
    assert_eq!(observed, Some(generation));
    drop(store);
    let reopened = fixture.store(PolicyStoreLimits::default());
    let current = reopened.capture_control_generation(deadline()).unwrap();
    assert_eq!(current.persisted_generation(), generation);
    let mut entered = false;
    assert!(reopened
        .with_control_generation(&captured, deadline(), &mut |_| {
            entered = true;
            Ok(())
        })
        .is_err());
    assert!(!entered);
}

#[test]
fn unrelated_policy_mutation_invalidates_capture_while_exact_receipt_replay_keeps_generation() {
    let fixture = Fixture::new();
    let store = fixture.store(PolicyStoreLimits::default());
    let bytes = serde_json::to_vec(&policy()).unwrap();
    mutate(&store, "p", "create", 0, Some(&bytes)).unwrap();
    let original = store.capture_control_generation(deadline()).unwrap();
    mutate(&store, "p", "create", 0, Some(&bytes)).unwrap();
    store
        .with_control_generation(&original, deadline(), &mut |_| Ok(()))
        .unwrap();
    mutate(&store, "other", "other-create", 0, Some(&bytes)).unwrap();
    let current = store.capture_control_generation(deadline()).unwrap();
    assert!(current.persisted_generation() > original.persisted_generation());
    let mut entered = false;
    assert!(store
        .with_control_generation(&original, deadline(), &mut |_| {
            entered = true;
            Ok(())
        })
        .is_err());
    assert!(!entered);
    store
        .with_control_generation(&current, deadline(), &mut |_| Ok(()))
        .unwrap();
}

#[test]
fn control_generation_shares_real_read_capacity_until_capture_destruction() {
    let fixture = Fixture::new();
    let store = fixture.store(PolicyStoreLimits {
        maximum_read_owners: 2,
        ..PolicyStoreLimits::default()
    });
    let first = store.capture_control_generation(deadline()).unwrap();
    let second = store.capture_control_generation(deadline()).unwrap();
    assert_eq!(store.retained_read_owners(), 2);
    let failure = store.capture_control_generation(deadline()).err().unwrap();
    assert_eq!(failure.code, PlatformErrorCode::ResourceExhausted);
    assert_eq!(store.retained_read_owners(), 2);
    drop(first);
    assert_eq!(store.retained_read_owners(), 1);
    let replacement = store.capture_control_generation(deadline()).unwrap();
    store.retire();
    assert!(store
        .with_control_generation(&second, deadline(), &mut |_| Ok(()))
        .is_err());
    assert_eq!(store.retained_read_owners(), 2);
    drop(second);
    drop(replacement);
    assert_eq!(store.retained_read_owners(), 0);
}

#[test]
fn control_generation_rejects_deadline_busy_fence_and_uncertain_owner_before_callback() {
    let fixture = Fixture::new();
    let store = fixture.store(PolicyStoreLimits::default());
    let captured = store.capture_control_generation(deadline()).unwrap();
    let mut entered = false;
    let mut action = |_| {
        entered = true;
        Ok(())
    };
    assert!(store
        .with_control_generation(&captured, Instant::now(), &mut action)
        .is_err());
    {
        let _held = store.owner.fence.try_write().unwrap();
        assert!(store.capture_control_generation(deadline()).is_err());
        assert!(store
            .with_control_generation(&captured, deadline(), &mut action)
            .is_err());
    }
    {
        let _held = store.state.try_lock().unwrap();
        assert!(store.capture_control_generation(deadline()).is_err());
        assert!(store
            .with_control_generation(&captured, deadline(), &mut action)
            .is_err());
    }
    store.owner.poison();
    assert!(store
        .with_control_generation(&captured, deadline(), &mut action)
        .is_err());
    assert!(!entered);
    assert_eq!(store.retained_read_owners(), 1);
}

#[test]
fn control_generation_callback_unwind_invalidates_original_owner_without_refunding_capture() {
    let fixture = Fixture::new();
    let store = fixture.store(PolicyStoreLimits::default());
    let captured = store.capture_control_generation(deadline()).unwrap();
    let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        store.with_control_generation(&captured, deadline(), &mut |_| {
            panic!("controlled installation callback cut")
        })
    }));
    assert!(result.is_err());
    assert!(!store.owner.healthy.load(Ordering::Acquire));
    assert!(store.capture_control_generation(deadline()).is_err());
    assert!(store
        .with_control_generation(&captured, deadline(), &mut |_| Ok(()))
        .is_err());
    assert_eq!(store.retained_read_owners(), 1);
    drop(captured);
    assert_eq!(store.retained_read_owners(), 0);
}
