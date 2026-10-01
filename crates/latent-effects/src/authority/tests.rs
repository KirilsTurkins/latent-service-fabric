use super::*;

#[test]
fn unretired_provider_context_quarantines_original_global_capacity_after_all_grants_drop() {
    use latent_core::native_capacity::{
        NativeAdmissionClass, NativeCapacityLimits, NativeCapacityOwner, NativeReservationRequest,
    };
    let capacity = NativeCapacityOwner::new(NativeCapacityLimits::default()).unwrap();
    let original = Arc::new(
        capacity
            .reserve(
                NativeAdmissionClass::Recovery,
                NativeReservationRequest {
                    request_bytes: 1,
                    work_bytes: 1,
                    response_bytes: 1,
                },
                Instant::now() + Duration::from_secs(30),
            )
            .unwrap(),
    );
    let witness = Arc::downgrade(&original);
    let (owner, _, authority) = setup();
    let mut context = owner.accept(&authority, 1, time(101)).unwrap();
    context
        .retain_owner(original.clone())
        .unwrap_or_else(|_| panic!("original owner refused"));
    let grant = context
        .accept_with(&authority, 1, time(102), |grant| grant)
        .unwrap();
    drop(original);
    drop(context);
    drop(grant);
    assert!(witness.upgrade().is_some());
    assert_eq!(capacity.snapshot().unwrap().recovery.slots, 1);
    assert_eq!(
        owner.owners().unwrap(),
        DispatchOwners {
            physical: 1,
            quarantined: 1
        }
    );
}

#[test]
fn provider_grant_retains_original_native_capacity_after_context_retirement_and_refuses_replacement(
) {
    use latent_core::native_capacity::{
        NativeAdmissionClass, NativeCapacityLimits, NativeCapacityOwner, NativeReservationRequest,
    };
    let mut limits = NativeCapacityLimits::default();
    limits.recovery.slots = 1;
    let capacity = NativeCapacityOwner::new(limits).unwrap();
    let original = Arc::new(
        capacity
            .reserve(
                NativeAdmissionClass::Recovery,
                NativeReservationRequest {
                    request_bytes: 4096,
                    work_bytes: 8192,
                    response_bytes: 4096,
                },
                Instant::now() + Duration::from_secs(30),
            )
            .unwrap(),
    );
    let witness = Arc::downgrade(&original);
    let (owner, _, authority) = setup();
    let mut context = owner.accept(&authority, 1, time(101)).unwrap();
    context
        .retain_owner(original.clone())
        .unwrap_or_else(|_| panic!("original owner refused"));
    let replacement: Arc<dyn std::any::Any + Send + Sync> = Arc::new("foreign");
    let refused = context
        .retain_owner(Arc::clone(&replacement))
        .err()
        .unwrap();
    assert!(Arc::ptr_eq(&replacement, &refused));
    let grant = context
        .accept_with(&authority, 1, time(102), |grant| grant)
        .unwrap();
    drop(original);
    context.retire().unwrap();
    assert_eq!(owner.owners().unwrap().physical, 0);
    assert!(witness.upgrade().is_some());
    assert_eq!(capacity.snapshot().unwrap().recovery.slots, 1);
    assert_eq!(grant.check_current(time(103)), Err(AuthorityError::Stale));
    drop(grant);
    assert!(witness.upgrade().is_none());
    assert_eq!(capacity.snapshot().unwrap().recovery.slots, 0);
    let mut later = owner.accept(&authority, 1, time(104)).unwrap();
    let grant = later
        .accept_with(&authority, 1, time(104), |grant| grant)
        .unwrap();
    let refused = later.retain_owner(Arc::clone(&replacement)).err().unwrap();
    assert!(Arc::ptr_eq(&replacement, &refused));
    drop(grant);
    later.retire().unwrap();
}

#[test]
fn namespace_close_invalidates_accepted_grants_without_refunding_physical_work() {
    let (owner, original, authority) = setup();
    let mut context = owner.accept(&authority, 1, time(101)).unwrap();
    let grant = context
        .accept_with(&authority, 1, time(102), |grant| grant)
        .unwrap();
    owner
        .prepare_namespace_close("tenant-a", "orders", 1)
        .unwrap()
        .accept(|| Ok::<(), ()>(()))
        .unwrap();
    assert_eq!(
        grant.check_current(time(103)),
        Err(AuthorityError::PolicyBlocked)
    );
    assert_eq!(owner.owners().unwrap().physical, 1);
    let mut newer = original.clone();
    newer.scope.publication = "publication-b".into();
    newer.policy_revision = 2;
    assert_eq!(
        owner.publish(newer.clone()),
        Err(AuthorityError::PolicyBlocked)
    );
    newer.scope.incarnation = 2;
    owner.publish(newer).unwrap();
    context.retire().unwrap();
    assert_eq!(owner.owners().unwrap(), DispatchOwners::default());
}

#[test]
fn rejected_namespace_acceptance_preserves_current_original_effect_rules() {
    let (owner, _, authority) = setup();
    let fence = owner
        .prepare_namespace_close("tenant-a", "orders", 1)
        .unwrap();
    assert!(matches!(
        owner.0.state.try_lock(),
        Err(std::sync::TryLockError::WouldBlock)
    ));
    assert_eq!(
        fence.accept(|| Err::<(), _>("original-request-closed")),
        Err("original-request-closed")
    );
    owner.retry_fence(&authority, 2, 200, time(101)).unwrap();
    assert!(owner.0.state.lock().unwrap().closed_namespaces.is_empty());
}

#[test]
fn sticky_namespace_close_is_exact_and_bounded_before_original_acceptance() {
    let owner = EffectAuthorityOwner::new(1, 1, 100).unwrap();
    let original = rule();
    owner.publish(original.clone()).unwrap();
    owner
        .prepare_namespace_close("tenant-b", "orders", 1)
        .unwrap()
        .accept(|| Ok::<(), ()>(()))
        .unwrap();
    assert!(matches!(
        owner.prepare_namespace_close("tenant-a", "orders", 1),
        Err(AuthorityError::Capacity)
    ));
    assert!(matches!(
        owner.prepare_namespace_close("tenant-a", "orders", 0),
        Err(AuthorityError::Invalid)
    ));
    assert!(
        owner
            .0
            .state
            .lock()
            .unwrap()
            .rules
            .get(&original.scope)
            .unwrap()
            .enabled
    );
    owner
        .prepare_namespace_close("tenant-b", "orders", 1)
        .unwrap()
        .accept(|| Ok::<(), ()>(()))
        .unwrap();
    assert_eq!(owner.0.state.lock().unwrap().closed_namespaces.len(), 1);
}

#[test]
fn explicit_redrive_intersects_narrowed_original_rules_through_final_acceptance() {
    let (owner, mut rule, authority) = setup();
    rule.policy_revision = 2;
    rule.ceiling.maximum_attempts = 2;
    owner.publish(rule).unwrap();
    let guard = owner.retry_fence(&authority, 2, 200, time(101)).unwrap();
    assert!(matches!(
        owner.0.state.try_lock(),
        Err(std::sync::TryLockError::WouldBlock)
    ));
    drop(guard);
    assert!(matches!(
        owner.retry_fence(&authority, 3, 200, time(102)),
        Err(AuthorityError::Capacity)
    ));
    assert!(matches!(
        owner.retry_fence(&authority, 2, authority.expires_at_millis, time(103)),
        Err(AuthorityError::Expired)
    ));
    assert_eq!(owner.owners().unwrap(), DispatchOwners::default());
}

#[test]
fn newer_publication_cannot_revive_revoked_original_redrive_scope() {
    let (owner, mut original, authority) = setup();
    original.policy_revision = 2;
    original.enabled = false;
    owner.publish(original.clone()).unwrap();
    let mut newer = original;
    newer.scope.publication = "pub-b".into();
    newer.enabled = true;
    owner.publish(newer).unwrap();
    assert!(matches!(
        owner.retry_fence(&authority, 2, 200, time(101)),
        Err(AuthorityError::PolicyBlocked)
    ));
    assert_eq!(owner.owners().unwrap(), DispatchOwners::default());
}

#[test]
fn final_adapter_admission_refreshes_credential_and_narrows_original_deadline_under_fence() {
    let (owner, mut rule, authority) = setup();
    let mut context = owner.accept(&authority, 1, time(101)).unwrap();
    let deadline = context.deadline();
    rule.policy_revision = 2;
    rule.credential_epoch = 2;
    rule.protected_credential_reference = "rotated-secret".into();
    rule.ceiling.maximum_response_bytes = 128;
    rule.ceiling.attempt_timeout_millis = 50;
    owner.publish(rule).unwrap();
    context
        .accept_with(&authority, 1, time(102), |grant| {
            assert_eq!(grant.effect(), authority.link().effect);
            assert_eq!(grant.attempt(), 1);
            assert_eq!(grant.scope(), authority.scope());
            assert_eq!(grant.profile(), authority.profile());
            assert_eq!(grant.credential_epoch(), 2);
            assert_eq!(grant.protected_credential_reference(), "rotated-secret");
            assert_eq!(grant.ceiling().maximum_response_bytes, 128);
            assert!(grant.deadline() <= deadline);
            assert!(matches!(
                owner.0.state.try_lock(),
                Err(std::sync::TryLockError::WouldBlock)
            ));
        })
        .unwrap();
    assert_eq!(owner.owners().unwrap().physical, 1);
    context.retire().unwrap();
    assert_eq!(owner.owners().unwrap(), DispatchOwners::default());
}

#[test]
fn revocation_between_claim_and_adapter_acceptance_prevents_io_without_refunding_physical_owner() {
    let (owner, mut rule, authority) = setup();
    let mut context = owner.accept(&authority, 1, time(101)).unwrap();
    assert_eq!(
        context.accept_with(&authority, 2, time(102), |_| panic!(
            "wrong attempt accepted"
        )),
        Err(AuthorityError::Invalid)
    );
    rule.policy_revision = 2;
    rule.enabled = false;
    owner.publish(rule).unwrap();
    assert_eq!(
        context.accept_with(&authority, 1, time(103), |_| panic!(
            "revoked adapter accepted"
        )),
        Err(AuthorityError::PolicyBlocked)
    );
    assert_eq!(owner.owners().unwrap().physical, 1);
    context.retire().unwrap();
    assert_eq!(owner.owners().unwrap(), DispatchOwners::default());
}

fn rule() -> EffectRule {
    EffectRule {
        scope: EffectScope {
            tenant: "tenant-a".into(),
            namespace: "orders".into(),
            incarnation: 1,
            publication: "publication-a".into(),
            binding: "events".into(),
            operation: "publish".into(),
        },
        profile: DispatchProfile {
            provider: "jetstream-a".into(),
            destination: "orders.subject".into(),
            adapter: "jetstream.v1".into(),
            intent_format: 1,
            payload_format: "bytes.v1".into(),
            idempotency_profile: "bounded-message-id.v1".into(),
        },
        policy_revision: 1,
        credential_epoch: 1,
        protected_credential_reference: "provider-a".into(),
        ceiling: DispatchCeiling {
            maximum_payload_bytes: 1024,
            maximum_response_bytes: 1024,
            maximum_attempts: 3,
            maximum_age_millis: 1000,
            attempt_timeout_millis: 100,
        },
        enabled: true,
    }
}

fn time(now: u64) -> EffectTime {
    EffectTime {
        unix_millis: now,
        continuity_proven: true,
    }
}

fn setup() -> (EffectAuthorityOwner, EffectRule, DurableEffectAuthority) {
    let owner = EffectAuthorityOwner::new(2, 2, 100).unwrap();
    let grant = rule();
    owner.publish(grant.clone()).unwrap();
    let link = CommitLink {
        command: "command-a".into(),
        caller_scope: "user-a".into(),
        attempt: 1,
        commit: "commit-a".into(),
        effect: "effect-a".into(),
        sequence: 0,
    };
    let captured = owner
        .capture(&grant.scope, link, 100, "a".repeat(64), time(100))
        .unwrap();
    (owner, grant, captured)
}

#[test]
fn commit_refresh_freezes_current_intersection_and_original_expiry_without_dispatch_work() {
    let (owner, mut grant, staged) = setup();
    grant.policy_revision = 2;
    grant.credential_epoch = 2;
    grant.protected_credential_reference = "rotated-secret".into();
    grant.ceiling.maximum_response_bytes = 128;
    grant.ceiling.maximum_attempts = 2;
    grant.ceiling.maximum_age_millis = 600;
    grant.ceiling.attempt_timeout_millis = 50;
    owner.publish(grant.clone()).unwrap();
    let committed = owner.refresh_for_commit(&staged, time(200)).unwrap();
    assert_eq!(committed.scope(), staged.scope());
    assert_eq!(committed.profile(), staged.profile());
    assert_eq!(committed.link(), staged.link());
    assert_eq!(committed.payload_digest(), staged.payload_digest());
    assert_eq!(committed.payload_bytes(), staged.payload_bytes());
    assert_eq!(committed.policy_revision, 2);
    assert_eq!(committed.committed_at_millis(), 200);
    assert_eq!(committed.expires_at_millis(), 800);
    assert_eq!(committed.ceiling().maximum_response_bytes, 128);
    assert_eq!(committed.ceiling().maximum_attempts, 2);
    assert_eq!(committed.ceiling().maximum_age_millis, 600);
    assert_eq!(committed.ceiling().attempt_timeout_millis, 50);
    assert_eq!(owner.owners().unwrap(), DispatchOwners::default());
    assert_eq!(
        DurableEffectAuthority::decode(&committed.encode().unwrap()),
        Ok(committed.clone())
    );

    grant.policy_revision = 3;
    grant.ceiling = rule().ceiling;
    owner.publish(grant).unwrap();
    let context = owner.accept(&committed, 1, time(201)).unwrap();
    assert_eq!(context.ceiling(), committed.ceiling());
    assert_eq!(context.credential_epoch(), 2);
    context.retire().unwrap();
    let late = owner.refresh_for_commit(&staged, time(1050)).unwrap();
    assert_eq!(late.committed_at_millis(), 1050);
    assert_eq!(late.expires_at_millis(), staged.expires_at_millis());
    assert_eq!(late.ceiling().maximum_age_millis, 50);
    assert_eq!(late.ceiling().attempt_timeout_millis, 50);
    assert_eq!(owner.owners().unwrap(), DispatchOwners::default());
}

#[test]
fn commit_refresh_rejects_profile_changes_expiry_and_unproven_time() {
    for profile in [
        DispatchProfile {
            provider: "other-provider".into(),
            ..rule().profile
        },
        DispatchProfile {
            destination: "other-subject".into(),
            ..rule().profile
        },
        DispatchProfile {
            adapter: "other-adapter".into(),
            ..rule().profile
        },
        DispatchProfile {
            intent_format: 2,
            ..rule().profile
        },
        DispatchProfile {
            payload_format: "bytes.v2".into(),
            ..rule().profile
        },
        DispatchProfile {
            idempotency_profile: "other-dedup".into(),
            ..rule().profile
        },
    ] {
        let (owner, mut grant, staged) = setup();
        grant.policy_revision = 2;
        grant.profile = profile;
        owner.publish(grant).unwrap();
        assert_eq!(
            owner.refresh_for_commit(&staged, time(101)),
            Err(AuthorityError::UnsupportedFormat)
        );
        assert_eq!(owner.owners().unwrap(), DispatchOwners::default());
    }
    let (owner, mut grant, staged) = setup();
    assert_eq!(
        owner.refresh_for_commit(
            &staged,
            EffectTime {
                unix_millis: 101,
                continuity_proven: false
            }
        ),
        Err(AuthorityError::ClockDiscontinuity)
    );
    assert_eq!(
        owner.refresh_for_commit(&staged, time(99)),
        Err(AuthorityError::ClockDiscontinuity)
    );
    grant.policy_revision = 2;
    grant.ceiling.maximum_payload_bytes = 99;
    owner.publish(grant.clone()).unwrap();
    assert_eq!(
        owner.refresh_for_commit(&staged, time(101)),
        Err(AuthorityError::Capacity)
    );
    grant.policy_revision = 3;
    grant.ceiling.maximum_payload_bytes = 100;
    owner.publish(grant.clone()).unwrap();
    assert_eq!(
        owner.refresh_for_commit(&staged, time(1100)),
        Err(AuthorityError::Expired)
    );
    let (owner, mut grant, staged) = setup();
    grant.policy_revision = 2;
    grant.enabled = false;
    owner.publish(grant).unwrap();
    assert_eq!(
        owner.refresh_for_commit(&staged, time(101)),
        Err(AuthorityError::PolicyBlocked)
    );
    assert_eq!(owner.owners().unwrap(), DispatchOwners::default());
}

#[test]
fn commit_fence_rejects_narrowing_after_refresh_and_allows_compatible_rotation() {
    let (owner, mut grant, staged) = setup();
    grant.policy_revision = 2;
    grant.ceiling.maximum_response_bytes = 512;
    owner.publish(grant.clone()).unwrap();
    let prepared = owner.refresh_for_commit(&staged, time(200)).unwrap();
    grant.policy_revision = 3;
    grant.ceiling.maximum_response_bytes = 256;
    owner.publish(grant.clone()).unwrap();
    assert!(matches!(
        owner.commit_fence(std::slice::from_ref(&prepared), time(201)),
        Err(AuthorityError::PolicyBlocked)
    ));
    assert_eq!(owner.owners().unwrap(), DispatchOwners::default());
    let prepared = owner.refresh_for_commit(&staged, time(202)).unwrap();
    let fence = owner
        .commit_fence(std::slice::from_ref(&prepared), time(203))
        .unwrap();
    assert!(matches!(
        owner.0.state.try_lock(),
        Err(std::sync::TryLockError::WouldBlock)
    ));
    drop(fence);
    grant.policy_revision = 4;
    grant.credential_epoch = 2;
    grant.protected_credential_reference = "rotated-secret".into();
    grant.ceiling = rule().ceiling;
    owner.publish(grant).unwrap();
    drop(
        owner
            .commit_fence(std::slice::from_ref(&prepared), time(204))
            .unwrap(),
    );
    let context = owner.accept(&prepared, 1, time(205)).unwrap();
    assert_eq!(context.ceiling().maximum_response_bytes, 256);
    assert_eq!(context.credential_epoch(), 2);
    context.retire().unwrap();
    assert_eq!(owner.owners().unwrap(), DispatchOwners::default());
}

#[test]
fn final_commit_fence_linearizes_revocation_without_allocating_dispatch_work() {
    use std::sync::mpsc;
    let (owner, mut grant, captured) = setup();
    let fence = owner
        .commit_fence(std::slice::from_ref(&captured), time(101))
        .unwrap();
    assert!(matches!(
        owner.0.state.try_lock(),
        Err(std::sync::TryLockError::WouldBlock)
    ));
    let worker_owner = owner.clone();
    grant.policy_revision = 2;
    grant.enabled = false;
    let (started_tx, started_rx) = mpsc::channel();
    let (finished_tx, finished_rx) = mpsc::channel();
    let worker = std::thread::spawn(move || {
        started_tx.send(()).unwrap();
        finished_tx.send(worker_owner.publish(grant)).unwrap();
    });
    started_rx.recv_timeout(Duration::from_secs(3)).unwrap();
    assert_eq!(finished_rx.try_recv(), Err(mpsc::TryRecvError::Empty));
    drop(fence);
    assert_eq!(
        finished_rx.recv_timeout(Duration::from_secs(3)).unwrap(),
        Ok(())
    );
    worker.join().unwrap();
    assert!(matches!(
        owner.commit_fence(&[captured], time(102)),
        Err(AuthorityError::PolicyBlocked)
    ));
    assert_eq!(owner.owners().unwrap(), DispatchOwners::default());
}

#[test]
fn final_commit_checks_every_intent_against_current_format_bounds_and_clock() {
    let (owner, mut grant, captured) = setup();
    grant.policy_revision = 2;
    grant.ceiling.maximum_payload_bytes = 99;
    owner.publish(grant.clone()).unwrap();
    assert!(matches!(
        owner.commit_fence(std::slice::from_ref(&captured), time(101)),
        Err(AuthorityError::Capacity)
    ));
    grant.policy_revision = 3;
    grant.ceiling.maximum_payload_bytes = 100;
    grant.profile.intent_format = 2;
    owner.publish(grant).unwrap();
    assert!(matches!(
        owner.commit_fence(&[captured], time(102)),
        Err(AuthorityError::UnsupportedFormat)
    ));
    assert!(matches!(
        owner.commit_fence(&[], time(101)),
        Err(AuthorityError::ClockDiscontinuity)
    ));
    assert_eq!(owner.owners().unwrap(), DispatchOwners::default());
}

#[test]
fn requested_expiry_only_narrows_and_malformed_typed_envelopes_grant_nothing() {
    let (owner, grant, captured) = setup();
    let short = owner
        .capture_until(
            &grant.scope,
            captured.link.clone(),
            100,
            "a".repeat(64),
            time(100),
            Some(200),
        )
        .unwrap();
    assert_eq!(short.ceiling().maximum_age_millis, 100);
    assert_eq!(
        DurableEffectAuthority::decode(&short.encode().unwrap()),
        Ok(short.clone())
    );
    let long = owner
        .capture_until(
            &grant.scope,
            captured.link.clone(),
            100,
            "a".repeat(64),
            time(100),
            Some(u64::MAX),
        )
        .unwrap();
    assert_eq!(long.ceiling(), captured.ceiling());
    assert_eq!(
        owner.capture_until(
            &grant.scope,
            captured.link.clone(),
            100,
            "a".repeat(64),
            time(100),
            Some(100)
        ),
        Err(AuthorityError::Invalid)
    );
    assert!(matches!(
        owner.commit_fence(&[short], time(200)),
        Err(AuthorityError::Expired)
    ));
    let mut forged = captured;
    forged.policy_revision = 0;
    assert_eq!(forged.encode(), Err(AuthorityError::Invalid));
    assert!(matches!(
        owner.accept(&forged, 1, time(201)),
        Err(AuthorityError::Invalid)
    ));
}

#[test]
fn guest_selected_alias_does_not_grant_cross_tenant_or_publication_authority() {
    let (owner, grant, captured) = setup();
    for forged in [
        EffectScope {
            tenant: "tenant-b".into(),
            ..grant.scope.clone()
        },
        EffectScope {
            publication: "publication-b".into(),
            ..grant.scope.clone()
        },
        EffectScope {
            incarnation: 2,
            ..grant.scope.clone()
        },
    ] {
        assert_eq!(
            owner.capture(
                &forged,
                captured.link.clone(),
                100,
                "a".repeat(64),
                time(101)
            ),
            Err(AuthorityError::PolicyBlocked)
        );
    }
    assert_eq!(owner.owners().unwrap(), DispatchOwners::default());
}

#[test]
fn current_ceiling_can_narrow_but_never_widen_a_committed_intent() {
    let (owner, mut grant, captured) = setup();
    grant.policy_revision = 2;
    grant.ceiling.maximum_payload_bytes = 100_000;
    grant.ceiling.maximum_attempts = 10;
    grant.ceiling.maximum_age_millis = 10_000;
    owner.publish(grant.clone()).unwrap();
    assert!(matches!(
        owner.accept(&captured, 4, time(101)),
        Err(AuthorityError::Capacity)
    ));
    let context = owner.accept(&captured, 1, time(102)).unwrap();
    assert_eq!(context.ceiling(), captured.ceiling);
    context.retire().unwrap();
    grant.policy_revision = 3;
    grant.ceiling.maximum_payload_bytes = 99;
    owner.publish(grant).unwrap();
    assert!(matches!(
        owner.accept(&captured, 2, time(103)),
        Err(AuthorityError::Capacity)
    ));
}

#[test]
fn revocation_after_acceptance_does_not_refund_live_physical_work() {
    let (owner, mut grant, captured) = setup();
    let context = owner.accept(&captured, 1, time(101)).unwrap();
    grant.enabled = false;
    grant.policy_revision = 2;
    owner.publish(grant).unwrap();
    assert!(matches!(
        owner.accept(&captured, 2, time(102)),
        Err(AuthorityError::PolicyBlocked)
    ));
    assert_eq!(owner.owners().unwrap().physical, 1);
    context.retire().unwrap();
    assert_eq!(owner.owners().unwrap(), DispatchOwners::default());
}

#[test]
fn credential_rotation_preserves_destination_and_envelope_provenance() {
    let (owner, mut grant, captured) = setup();
    grant.credential_epoch = 2;
    grant.policy_revision = 2;
    grant.protected_credential_reference = "protected-reference-b".into();
    owner.publish(grant).unwrap();
    let context = owner.accept(&captured, 1, time(101)).unwrap();
    assert_eq!(context.credential_epoch(), 2);
    assert_eq!(
        context.protected_credential_reference(),
        "protected-reference-b"
    );
    assert_eq!(context.profile(), &captured.profile);
    assert!(!format!("{captured:?}").contains("protected-reference"));
    context.retire().unwrap();
}

#[test]
fn provider_replacement_and_old_decoder_removal_block_instead_of_redirecting() {
    let (owner, grant, captured) = setup();
    for profile in [
        DispatchProfile {
            destination: "another.subject".into(),
            ..grant.profile.clone()
        },
        DispatchProfile {
            intent_format: 2,
            ..grant.profile.clone()
        },
        DispatchProfile {
            idempotency_profile: "unqualified.v1".into(),
            ..grant.profile.clone()
        },
    ] {
        let changed = EffectRule {
            policy_revision: 2,
            profile,
            ..grant.clone()
        };
        let replacement = EffectAuthorityOwner::new(2, 2, 100).unwrap();
        replacement.publish(changed).unwrap();
        assert!(matches!(
            replacement.accept(&captured, 1, time(101)),
            Err(AuthorityError::UnsupportedFormat)
        ));
    }
    assert_eq!(owner.owners().unwrap(), DispatchOwners::default());
}

#[test]
fn expiry_and_uncertain_restart_clock_never_renew_durable_lifetime() {
    let (owner, _, captured) = setup();
    assert!(matches!(
        owner.accept(
            &captured,
            1,
            EffectTime {
                unix_millis: 101,
                continuity_proven: false
            }
        ),
        Err(AuthorityError::ClockDiscontinuity)
    ));
    assert!(matches!(
        owner.accept(&captured, 1, time(99)),
        Err(AuthorityError::ClockDiscontinuity)
    ));
    assert!(matches!(
        owner.accept(&captured, 1, time(1100)),
        Err(AuthorityError::Expired)
    ));
    assert!(matches!(
        owner.accept(&captured, 1, time(101)),
        Err(AuthorityError::ClockDiscontinuity)
    ));
}

#[test]
fn dropped_context_quarantines_capacity_instead_of_refunding_live_io() {
    let (owner, _, captured) = setup();
    let first = owner.accept(&captured, 1, time(101)).unwrap();
    let second = owner.accept(&captured, 2, time(102)).unwrap();
    drop(first);
    assert_eq!(
        owner.owners().unwrap(),
        DispatchOwners {
            physical: 2,
            quarantined: 1
        }
    );
    assert!(matches!(
        owner.accept(&captured, 3, time(103)),
        Err(AuthorityError::Capacity)
    ));
    second.retire().unwrap();
    assert_eq!(
        owner.owners().unwrap(),
        DispatchOwners {
            physical: 1,
            quarantined: 1
        }
    );
}

#[test]
fn bounded_rule_publication_rejects_rollback_and_same_revision_mutation() {
    let (owner, mut grant, _) = setup();
    grant.enabled = false;
    assert_eq!(owner.publish(grant.clone()), Err(AuthorityError::Stale));
    grant.policy_revision = 2;
    owner.publish(grant.clone()).unwrap();
    grant.policy_revision = 1;
    assert_eq!(owner.publish(grant), Err(AuthorityError::Stale));
    let mut extra = rule();
    extra.scope.tenant = "tenant-b".into();
    owner.publish(extra.clone()).unwrap();
    extra.scope.tenant = "tenant-c".into();
    assert_eq!(owner.publish(extra), Err(AuthorityError::Capacity));
}

#[test]
fn bounded_retained_record_roundtrip_never_restores_current_authority() {
    let (owner, mut grant, captured) = setup();
    let bytes = captured.encode().unwrap();
    let retained = DurableEffectAuthority::decode(&bytes).unwrap();
    assert_eq!(retained, captured);
    grant.enabled = false;
    grant.policy_revision = 2;
    owner.publish(grant).unwrap();
    assert!(matches!(
        owner.accept(&retained, 1, time(101)),
        Err(AuthorityError::PolicyBlocked)
    ));
    let mut newer = bytes.clone();
    newer[4] = 2;
    assert_eq!(
        DurableEffectAuthority::decode(&newer),
        Err(AuthorityError::UnsupportedFormat)
    );
    assert_eq!(
        DurableEffectAuthority::decode(&vec![0; 8198]),
        Err(AuthorityError::Capacity)
    );
    let mut body: serde_json::Value = serde_json::from_slice(&bytes[5..]).unwrap();
    body["ceiling"]["maximum_attempts"] = serde_json::json!(0);
    let mut corrupt = b"LEA\0\x01".to_vec();
    corrupt.extend(serde_json::to_vec(&body).unwrap());
    assert_eq!(
        DurableEffectAuthority::decode(&corrupt),
        Err(AuthorityError::Invalid)
    );
    body["ceiling"]["maximum_attempts"] = serde_json::json!(3);
    body["credential"] = serde_json::json!("untrusted");
    corrupt.truncate(5);
    corrupt.extend(serde_json::to_vec(&body).unwrap());
    assert_eq!(
        DurableEffectAuthority::decode(&corrupt),
        Err(AuthorityError::Invalid)
    );
}

#[test]
fn retained_grant_rechecks_original_owner_revocation_profile_ceiling_and_credential_epoch() {
    for change in 0..5 {
        let (owner, mut current, authority) = setup();
        let mut context = owner.accept(&authority, 1, time(101)).unwrap();
        let grant = context
            .accept_with(&authority, 1, time(102), |grant| grant)
            .unwrap();
        let original_deadline = grant.deadline();
        let foreign = EffectAuthorityOwner::new(2, 2, 100).unwrap();
        let mut foreign_rule = current.clone();
        foreign_rule.enabled = false;
        foreign.publish(foreign_rule).unwrap();
        assert_eq!(grant.check_current(time(103)), Ok(()));
        current.policy_revision = 2;
        let expected = match change {
            0 => {
                current.enabled = false;
                AuthorityError::PolicyBlocked
            }
            1 => {
                current.profile.adapter = "replacement-adapter".into();
                AuthorityError::UnsupportedFormat
            }
            2 => {
                current.ceiling.maximum_response_bytes -= 1;
                AuthorityError::Capacity
            }
            3 => {
                current.credential_epoch += 1;
                AuthorityError::PolicyBlocked
            }
            _ => {
                current.protected_credential_reference = "replacement-secret".into();
                AuthorityError::PolicyBlocked
            }
        };
        owner.publish(current).unwrap();
        assert_eq!(grant.check_current(time(104)), Err(expected));
        assert_eq!(grant.deadline(), original_deadline);
        assert_eq!(owner.owners().unwrap().physical, 1);
        context.retire().unwrap();
        assert_eq!(grant.check_current(time(105)), Err(AuthorityError::Stale));
        assert_eq!(owner.owners().unwrap(), DispatchOwners::default());
    }
}

#[test]
fn retained_grant_compatible_widening_preserves_original_ceiling_expiry_deadline_and_clock() {
    let (owner, mut current, authority) = setup();
    current.policy_revision = 2;
    current.ceiling.maximum_age_millis = 200;
    owner.publish(current.clone()).unwrap();
    let mut context = owner.accept(&authority, 1, time(101)).unwrap();
    let grant = context
        .accept_with(&authority, 1, time(102), |grant| grant)
        .unwrap();
    let deadline = grant.deadline();
    let ceiling = grant.ceiling();
    current.policy_revision = 3;
    current.ceiling.maximum_age_millis = 2000;
    current.ceiling.maximum_response_bytes = 4096;
    current.ceiling.maximum_attempts = 8;
    owner.publish(current).unwrap();
    assert_eq!(grant.check_current(time(299)), Ok(()));
    assert_eq!(grant.deadline(), deadline);
    assert_eq!(grant.ceiling(), ceiling);
    assert_eq!(grant.check_current(time(300)), Err(AuthorityError::Expired));
    assert_eq!(
        grant.check_current(time(299)),
        Err(AuthorityError::ClockDiscontinuity)
    );
    assert_eq!(
        grant.check_current(EffectTime {
            unix_millis: 301,
            continuity_proven: false
        }),
        Err(AuthorityError::ClockDiscontinuity)
    );
    assert_eq!(owner.owners().unwrap().physical, 1);
    context.retire().unwrap();
}

#[test]
fn retired_or_quarantined_attempt_cannot_reauthorize_its_grant_through_another_live_owner() {
    let (owner, _, authority) = setup();
    let mut first = owner.accept(&authority, 1, time(101)).unwrap();
    let first_grant = first
        .accept_with(&authority, 1, time(102), |grant| grant)
        .unwrap();
    let mut second = owner.accept(&authority, 2, time(103)).unwrap();
    let second_grant = second
        .accept_with(&authority, 2, time(104), |grant| grant)
        .unwrap();
    first.retire().unwrap();
    assert_eq!(
        first_grant.check_current(time(105)),
        Err(AuthorityError::Stale)
    );
    assert_eq!(second_grant.check_current(time(105)), Ok(()));
    assert_eq!(owner.owners().unwrap().physical, 1);
    drop(second);
    assert_eq!(
        second_grant.check_current(time(106)),
        Err(AuthorityError::Stale)
    );
    assert_eq!(
        owner.owners().unwrap(),
        DispatchOwners {
            physical: 1,
            quarantined: 1
        }
    );
}
