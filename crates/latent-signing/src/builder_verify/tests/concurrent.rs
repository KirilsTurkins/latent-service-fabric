use super::support::*;
use super::*;

#[test]
fn currentness_readers_share_trust_without_spurious_resource_exhaustion() {
    let (signer, public, _) = signer(BUILDER);
    let evidence = signed(&signer, &observation());
    let owner = Arc::new(verifier(&policy_value(&public)));
    let proof = owner
        .verify_package(&subject(), evidence.as_ref(), NOW)
        .unwrap();
    let expected = owner.state_id().unwrap();
    let guard = owner.state.read().unwrap();
    let worker_owner = owner.clone();
    let (sender, receiver) = mpsc::sync_channel(1);
    let worker = thread::spawn(move || {
        let result = worker_owner
            .check_current(&proof, NOW)
            .and_then(|()| worker_owner.state_id())
            .and_then(|id| {
                worker_owner
                    .verify_package(&subject(), evidence.as_ref(), NOW)
                    .map(|fresh| (id, fresh.state_id().clone(), fresh.valid_until()))
            });
        sender.send(result).unwrap();
    });
    let before_unlock = receiver.recv_timeout(Duration::from_secs(1));
    drop(guard);
    worker.join().unwrap();
    let (id, fresh_id, expiry) = before_unlock.unwrap().unwrap();
    assert_eq!(id, expected);
    assert_eq!(fresh_id, expected);
    assert_eq!(expiry, NOW + 60);
    assert_eq!(owner.clock_floor(), NOW);
}

#[test]
fn exclusive_writer_refuses_currentness_without_queuing_or_renewing_proof() {
    let (signer, public, _) = signer(BUILDER);
    let evidence = signed(&signer, &observation());
    let mut policy = policy_value(&public);
    let owner = Arc::new(verifier(&policy));
    let proof = owner
        .verify_package(&subject(), evidence.as_ref(), NOW)
        .unwrap();
    let initial = owner.state_id().unwrap();
    let guard = owner.state.write().unwrap();
    let worker_owner = owner.clone();
    let (sender, receiver) = mpsc::sync_channel(1);
    let worker = thread::spawn(move || {
        sender
            .send(worker_owner.check_current(&proof, NOW + 1))
            .unwrap();
    });
    let before_unlock = receiver.recv_timeout(Duration::from_secs(1));
    drop(guard);
    worker.join().unwrap();
    assert_eq!(
        before_unlock.unwrap().unwrap_err().reason(),
        SignatureFailure::ResourceLimit
    );
    assert_eq!(owner.clock_floor(), NOW + 1);
    assert_eq!(owner.state_id().unwrap(), initial);
    let proof = owner
        .verify_package(&subject(), evidence.as_ref(), NOW + 1)
        .unwrap();
    policy["generation"] = 2.into();
    let next = owner
        .replace_trust(&initial, trust(&policy, |_| {}), NOW + 1)
        .unwrap();
    assert_ne!(next, initial);
    assert_eq!(
        owner.check_current(&proof, NOW + 1).unwrap_err().reason(),
        SignatureFailure::StaleProof
    );
    policy["generation"] = 3.into();
    assert_eq!(
        owner
            .replace_trust(&initial, trust(&policy, |_| {}), NOW + 1)
            .unwrap_err()
            .reason(),
        SignatureFailure::TrustConflict
    );
}

#[test]
fn poisoned_writer_keeps_proof_reads_and_trust_replacement_closed() {
    let (signer, public, _) = signer(BUILDER);
    let evidence = signed(&signer, &observation());
    let mut policy = policy_value(&public);
    let owner = Arc::new(verifier(&policy));
    let proof = owner
        .verify_package(&subject(), evidence.as_ref(), NOW)
        .unwrap();
    let initial = owner.state_id().unwrap();
    let worker_owner = owner.clone();
    let worker = thread::spawn(move || {
        let _guard = worker_owner.state.write().unwrap();
        panic!("poison the exclusive trust replacement owner");
    });
    assert!(worker.join().is_err());
    assert_eq!(
        owner.check_current(&proof, NOW).unwrap_err().reason(),
        SignatureFailure::Internal
    );
    assert_eq!(
        owner.state_id().unwrap_err().reason(),
        SignatureFailure::Internal
    );
    policy["generation"] = 2.into();
    assert_eq!(
        owner
            .replace_trust(&initial, trust(&policy, |_| {}), NOW + 1)
            .unwrap_err()
            .reason(),
        SignatureFailure::Internal
    );
    assert_eq!(owner.clock_floor(), NOW + 1);
}
