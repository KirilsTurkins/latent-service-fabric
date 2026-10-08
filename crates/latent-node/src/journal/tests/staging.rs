use super::*;
use latent_core::{BudgetProfile, EffectiveActivationBudget};
use latent_executor::transaction::{TransactionStagingIdentity, TransactionStagingProgress};

fn identity() -> TransactionStagingIdentity {
    TransactionStagingIdentity {
        command_id: "1".repeat(64),
        attempt_id: "2".repeat(64),
        transaction_id: "3".repeat(64),
        publication_id: format!("publication:sha256:{}", "4".repeat(64)),
    }
}

fn admitted(journal: &LocalActivationJournal, id: &str) -> super::super::owner::JournalOwner {
    let mut input = envelope(id);
    input.budget.state_write_bytes = 40_000;
    input.budget.effect_count = 2;
    let grant = EffectiveActivationBudget::admit_profile_at(
        BudgetProfile::Phase4,
        &input.budget,
        &input.budget,
        &input.budget,
        None,
        journal.inner.clock.sample(),
    )
    .unwrap();
    let budget = latent_core::ActivationBudget::with_profile(grant, BudgetProfile::Phase4).unwrap();
    let mut owner = journal.begin(&input).unwrap();
    owner
        .advance(ActivationPhase::Resolved, Metadata::new())
        .unwrap();
    owner
        .advance(ActivationPhase::Admitted, Metadata::new())
        .unwrap();
    owner.record_grant(&budget);
    owner
}

fn running(owner: &mut super::super::owner::JournalOwner) {
    for phase in [
        ActivationPhase::Queued,
        ActivationPhase::Materializing,
        ActivationPhase::Running,
    ] {
        owner.advance(phase, Metadata::new()).unwrap();
    }
}

fn node(journal: &LocalActivationJournal, id: &str) -> super::super::ActivationTreeNode {
    journal
        .inspect_tree(
            &TenantId("tenant".into()),
            &ActivationId(id.into()),
            32,
            None,
        )
        .unwrap()
        .nodes
        .remove(0)
}

fn progress(count: u32) -> TransactionStagingProgress {
    TransactionStagingProgress {
        staged_mutations: count,
        captured_intents: count,
        state_write_bytes: u64::from(count) * 17_000,
    }
}

#[test]
fn staging_observer_requires_positive_progress_and_preserves_original_tree_and_root_scope() {
    let (journal, clock) = journal(2, 2);
    let mut owner = admitted(&journal, "command");
    let serial = owner.serial();
    let observer = owner.staging_observer(identity()).unwrap();
    assert!(node(&journal, "command").transaction_staging.is_none());
    observer.observe(progress(1));
    assert!(
        node(&journal, "command").transaction_staging.is_none(),
        "admission is not staging"
    );
    running(&mut owner);
    clock.wall(2000);
    observer.observe(progress(1));
    let witness = node(&journal, "command").transaction_staging.unwrap();
    assert_eq!(witness.activation_serial, serial);
    assert_eq!(witness.command_id, identity().command_id);
    assert_eq!(witness.attempt_id, identity().attempt_id);
    assert_eq!(witness.transaction_id, identity().transaction_id);
    assert_eq!(witness.publication_id, identity().publication_id);
    assert_eq!(witness.observed_at_unix_millis, 2000);
    assert_eq!(
        (
            witness.staged_mutations,
            witness.captured_intents,
            witness.state_write_bytes
        ),
        (1, 1, 17_000)
    );
    let roots = journal
        .inspect_roots(
            &TenantId("tenant".into()),
            &latent_core::ServiceId("service".into()),
            None,
            32,
            None,
        )
        .unwrap();
    assert_eq!(roots.nodes[0].transaction_staging.as_ref(), Some(&witness));
    assert!(journal
        .inspect_tree(
            &TenantId("foreign".into()),
            &ActivationId("command".into()),
            32,
            None
        )
        .unwrap()
        .nodes
        .is_empty());
    assert!(journal
        .inspect_roots(
            &TenantId("foreign".into()),
            &latent_core::ServiceId("service".into()),
            None,
            32,
            None
        )
        .unwrap()
        .nodes
        .is_empty());
    owner.finish(outcome());
    assert_eq!(node(&journal, "command").transaction_staging, Some(witness));
}

#[test]
fn staging_identity_and_one_owner_charge_refuse_malformed_duplicate_and_unadmitted_binding() {
    let (journal, clock) = journal(2, 2);
    let received = journal.begin(&envelope("received")).unwrap();
    assert!(received.staging_observer(identity()).is_err());
    let owner = admitted(&journal, "command");
    let before = journal.inner.lock().records[&ActivationId("command".into())].bytes;
    for field in 0..4 {
        let mut invalid = identity();
        match field {
            0 => invalid.command_id = "A".repeat(64),
            1 => invalid.attempt_id.push('0'),
            2 => invalid.transaction_id = "credential\nbytes".into(),
            _ => invalid.publication_id = format!("sha256:{}", "4".repeat(64)),
        }
        assert_eq!(
            owner.staging_observer(invalid).err().unwrap().code,
            PlatformErrorCode::InvalidArgument
        );
    }
    assert_eq!(
        journal.inner.lock().records[&ActivationId("command".into())].bytes,
        before
    );
    let _original = owner.staging_observer(identity()).unwrap();
    assert_eq!(
        journal.inner.lock().records[&ActivationId("command".into())].bytes,
        before + 2048
    );
    assert_eq!(
        owner.staging_observer(identity()).err().unwrap().code,
        PlatformErrorCode::PermissionDenied
    );
    assert_eq!(
        journal.inner.lock().records[&ActivationId("command".into())].bytes,
        before + 2048
    );
    let maximum_record_bytes = super::super::TERMINAL_RESERVE_BYTES + before + 2047;
    let bounded = LocalActivationJournal::new(
        LocalActivationJournalConfig {
            maximum_record_bytes,
            maximum_retained_bytes: maximum_record_bytes,
            maximum_active: 1,
            maximum_terminal: 1,
            terminal_retention: Duration::from_secs(1),
        },
        clock,
    )
    .unwrap();
    let bounded_owner = admitted(&bounded, "command");
    assert_eq!(
        bounded_owner
            .staging_observer(identity())
            .err()
            .unwrap()
            .code,
        PlatformErrorCode::ResourceExhausted
    );
    assert!(node(&bounded, "command").transaction_staging.is_none());
    assert_eq!(
        bounded.inner.lock().records[&ActivationId("command".into())].bytes,
        before
    );
    drop(received);
    drop(owner);
}

#[test]
fn staging_progress_rejects_metadata_forgery_zero_skips_budget_excess_and_regressions() {
    let (journal, _) = journal(2, 2);
    let mut forged = envelope("forged");
    forged
        .metadata
        .insert("transactionStaging".into(), "captured_intents=1".into());
    let mut forged_owner = journal.begin(&forged).unwrap();
    forged_owner
        .advance(
            ActivationPhase::Resolved,
            Metadata::from([("transactionStaging".into(), "captured_intents=1".into())]),
        )
        .unwrap();
    assert!(node(&journal, "forged").transaction_staging.is_none());
    let mut owner = admitted(&journal, "command");
    let observer = owner.staging_observer(identity()).unwrap();
    running(&mut owner);
    for invalid in [
        progress(0),
        progress(2),
        progress(3),
        TransactionStagingProgress {
            staged_mutations: 129,
            ..progress(1)
        },
        TransactionStagingProgress {
            state_write_bytes: 40_001,
            ..progress(1)
        },
    ] {
        observer.observe(invalid);
        assert!(node(&journal, "command").transaction_staging.is_none());
    }
    observer.observe(progress(1));
    let original = node(&journal, "command").transaction_staging.unwrap();
    for invalid in [
        progress(1),
        progress(3),
        TransactionStagingProgress {
            staged_mutations: 0,
            ..progress(2)
        },
        TransactionStagingProgress {
            state_write_bytes: 16_999,
            ..progress(2)
        },
    ] {
        observer.observe(invalid);
        assert_eq!(
            node(&journal, "command").transaction_staging.as_ref(),
            Some(&original)
        );
    }
    observer.observe(progress(2));
    assert_eq!(
        node(&journal, "command")
            .transaction_staging
            .unwrap()
            .captured_intents,
        2
    );
    drop(forged_owner);
    drop(owner);
}

#[test]
fn accepted_cancellation_is_not_terminal_and_terminal_observers_cannot_overwrite_staging() {
    let (journal, _) = journal(1, 2);
    let mut owner = admitted(&journal, "command");
    let observer = owner.staging_observer(identity()).unwrap();
    running(&mut owner);
    assert_eq!(
        journal
            .cancel_with(
                &TenantId("tenant".into()),
                &ActivationId("command".into()),
                || Ok(CancelDisposition::Accepted)
            )
            .unwrap(),
        CancelDisposition::Accepted
    );
    observer.observe(progress(1));
    let original = node(&journal, "command").transaction_staging.unwrap();
    owner.finish(ActivationOutcome::Failed {
        terminal_state: ActivationTerminalState::Cancelled,
        error: error(PlatformErrorCode::Cancelled, "cancelled"),
        consumption: BudgetConsumption::default(),
    });
    observer.observe(progress(2));
    assert_eq!(
        node(&journal, "command").transaction_staging,
        Some(original)
    );
    assert_eq!(
        node(&journal, "command").terminal_state,
        Some(ActivationTerminalState::Cancelled)
    );
}

#[test]
fn expired_retention_and_reused_activation_ids_reject_the_original_serial_observer() {
    let (journal, clock) = journal(1, 2);
    let mut original = admitted(&journal, "reused");
    let original_serial = original.serial();
    let stale = original.staging_observer(identity()).unwrap();
    running(&mut original);
    stale.observe(progress(1));
    original.finish(outcome());
    clock.elapse(Duration::from_secs(2));
    assert_eq!(journal.snapshot().terminal, 0);
    let mut replacement = admitted(&journal, "reused");
    assert_ne!(replacement.serial(), original_serial);
    let current = replacement.staging_observer(identity()).unwrap();
    running(&mut replacement);
    stale.observe(progress(1));
    assert!(node(&journal, "reused").transaction_staging.is_none());
    current.observe(progress(1));
    let witness = node(&journal, "reused").transaction_staging.unwrap();
    stale.observe(progress(2));
    assert_eq!(
        node(&journal, "reused").transaction_staging.as_ref(),
        Some(&witness)
    );
    replacement.finish(outcome());
    drop(journal);
    current.observe(progress(2));
}
