use super::*;
use latent_core::diagnostic::{ActivationDiagnostic, DiagnosticReason, DiagnosticStage};
use latent_core::{PrincipalKind, ServiceId};

fn child(id: &str, parent: &str, root: &str) -> ActivationEnvelope {
    let mut value = envelope(id);
    value.parent_activation_id = Some(ActivationId(parent.into()));
    value.root_activation_id = ActivationId(root.into());
    value
}

#[test]
fn root_discovery_is_scoped_bounded_filtered_and_keeps_one_serial_horizon() {
    let (initial, clock) = journal(4, 400);
    assert!(initial
        .inspect_roots(
            &TenantId("tenant".into()),
            &ServiceId("http-adapter".into()),
            None,
            32,
            None
        )
        .unwrap()
        .nodes
        .is_empty());
    let journal = LocalActivationJournal::new(
        LocalActivationJournalConfig {
            maximum_retained_bytes: 8 * 1024 * 1024,
            ..initial.inner.config
        },
        clock.clone(),
    )
    .unwrap();
    let tenant = TenantId("tenant".into());
    let service = ServiceId("http-adapter".into());
    for serial in 0..300 {
        journal
            .begin(&envelope(&format!("other-{serial}")))
            .unwrap()
            .finish(outcome());
    }
    clock.wall(2000);
    let mut actual = envelope("real-ingress-root");
    actual.target.service = service.clone();
    actual.principal.kind = PrincipalKind::Trigger;
    let root = journal.begin(&actual).unwrap();
    journal
        .begin(&child(
            "real-domain-child",
            "real-ingress-root",
            "real-ingress-root",
        ))
        .unwrap()
        .finish(outcome());
    let first = journal
        .inspect_roots(&tenant, &service, Some(2000), 32, None)
        .unwrap();
    assert!(
        first.nodes.is_empty(),
        "the finite scan ceiling can produce an empty page"
    );
    let cursor = first.next_page_token.unwrap();
    assert!(journal
        .inspect_roots(
            &TenantId("foreign".into()),
            &service,
            Some(2000),
            32,
            Some(&cursor)
        )
        .is_err());
    assert!(journal
        .inspect_roots(
            &tenant,
            &ServiceId("other".into()),
            Some(2000),
            32,
            Some(&cursor)
        )
        .is_err());
    assert!(journal
        .inspect_roots(&tenant, &service, None, 32, Some(&cursor))
        .is_err());
    let mut later = envelope("later-ingress");
    later.target.service = service.clone();
    journal.begin(&later).unwrap().finish(outcome());
    let next = journal
        .inspect_roots(&tenant, &service, Some(2000), 32, Some(&cursor))
        .unwrap();
    assert_eq!(
        next.nodes.len(),
        1,
        "new roots stay outside the original horizon"
    );
    assert_eq!(next.nodes[0].activation_id.0, "real-ingress-root");
    assert_eq!(next.nodes[0].principal_kind, PrincipalKind::Trigger);
    assert_eq!(next.nodes[0].target_service, service);
    assert_eq!(next.nodes[0].received_at_unix_millis, 2000);
    assert!(next.nodes[0].parent_activation_id.is_none());
    assert!(next.next_page_token.is_none());
    assert_eq!(
        journal
            .inspect_tree(&tenant, &next.nodes[0].activation_id, 32, None)
            .unwrap()
            .nodes
            .len(),
        2
    );
    assert!(journal
        .inspect_roots(&tenant, &service, Some(2001), 32, None)
        .unwrap()
        .nodes
        .is_empty());
    // New children under an old root must neither join root membership nor
    // produce an invalid cursor when the finite scan advances past the horizon.
    for serial in 0..300 {
        journal
            .begin(&child(
                &format!("late-child-{serial}"),
                "real-ingress-root",
                "real-ingress-root",
            ))
            .unwrap()
            .finish(outcome());
    }
    let again = journal
        .inspect_roots(&tenant, &service, Some(2000), 32, Some(&cursor))
        .unwrap();
    assert_eq!(again.nodes.len(), 1);
    let late_cursor = again.next_page_token.unwrap();
    let tail = journal
        .inspect_roots(&tenant, &service, Some(2000), 32, Some(&late_cursor))
        .unwrap();
    assert!(tail.nodes.is_empty() && tail.next_page_token.is_none());
    root.finish(outcome());
}

#[test]
fn failed_preparation_child_is_visible_before_any_guest_or_capability_event() {
    let (journal, _) = journal(4, 4);
    let root = envelope("parent");
    let parent = journal.begin(&root).unwrap();
    let mut failure = error(PlatformErrorCode::ResourceExhausted, "secret type / path");
    let mut diagnostic = ActivationDiagnostic::new(
        DiagnosticStage::Preparation,
        DiagnosticReason::SignatureAllocationLimit,
    );
    diagnostic.configured_bound = Some(16);
    diagnostic.calculated_requirement = Some(32);
    failure.details.push(diagnostic.detail());
    journal
        .begin(&child("failed-child", "parent", "parent"))
        .unwrap()
        .finish(ActivationOutcome::Failed {
            error: failure,
            terminal_state: ActivationTerminalState::ResourceExhausted,
            consumption: BudgetConsumption::default(),
        });
    let page = journal
        .inspect_tree(&root.target.tenant, &root.activation_id, 0, None)
        .unwrap();
    assert_eq!(page.nodes.len(), 2);
    assert_eq!(page.nodes[1].diagnostic, Some(diagnostic));
    assert!(page.nodes[1].diagnostic_is_terminal);
    assert_eq!(page.nodes[1].phase, ActivationPhase::Received);
    assert_eq!(
        page.nodes[1].parent_activation_id.as_ref().unwrap().0,
        "parent"
    );
    assert!(!format!("{page:?}").contains("secret"));
    parent.finish(outcome());
}

#[test]
fn mapped_codec_trap_retains_terminal_observation_and_consumption_in_the_tree() {
    use latent_executor::{GuestOutcome, GuestTrap};

    let (journal, _) = journal(3, 3);
    let root = envelope("codec-parent");
    let parent = journal.begin(&root).unwrap();
    let observation = ActivationDiagnostic::new(
        DiagnosticStage::Execution,
        DiagnosticReason::ValueAllocationLimit,
    );
    let consumption = BudgetConsumption {
        cpu_fuel: 17,
        peak_memory_bytes: 23,
        wall_time_micros: 29,
        ..BudgetConsumption::default()
    };
    for (id, diagnostic) in [
        ("typed-codec-child", Some(observation.clone())),
        ("unknown-codec-child", None),
    ] {
        let actual = child(id, "codec-parent", "codec-parent");
        let mut owner = journal.begin(&actual).unwrap();
        for phase in [
            ActivationPhase::Resolved,
            ActivationPhase::Admitted,
            ActivationPhase::Queued,
            ActivationPhase::Materializing,
            ActivationPhase::Running,
        ] {
            owner.advance(phase, Metadata::new()).unwrap();
        }
        let mapped = crate::activation_runner::map_execution_outcome(
            Ok(GuestOutcome::Trapped {
                trap: GuestTrap {
                    code: "result-limit-exceeded".into(),
                    message: "private-result-message".into(),
                    guest_backtrace: vec!["private-backtrace".into()],
                    metadata: Metadata::from([(
                        "result-codec-error".into(),
                        "ResourceExhausted".into(),
                    )]),
                    diagnostic,
                },
                consumption: consumption.clone(),
            }),
            "cell-test",
            "released",
        );
        let ActivationOutcome::Failed {
            terminal_state,
            error,
            consumption: recorded,
        } = &mapped
        else {
            panic!("codec failures must remain guest traps");
        };
        assert_eq!(*terminal_state, ActivationTerminalState::GuestTrap);
        assert_eq!(error.code, PlatformErrorCode::GuestTrap);
        assert!(!error.retryable);
        assert_eq!(recorded, &consumption);
        owner.validate_terminal(&mapped).unwrap();
        owner.finish(mapped);
        let page = journal
            .inspect_tree(&root.target.tenant, &actual.activation_id, 0, None)
            .unwrap();
        let node = page
            .nodes
            .iter()
            .find(|node| node.activation_id == actual.activation_id)
            .unwrap();
        assert_eq!(
            node.terminal_state,
            Some(ActivationTerminalState::GuestTrap)
        );
        assert_eq!(node.phase, ActivationPhase::Running);
        assert_eq!(
            node.diagnostic,
            if id == "typed-codec-child" {
                Some(observation.clone())
            } else {
                None
            }
        );
        assert_eq!(node.diagnostic_is_terminal, id == "typed-codec-child");
        assert_eq!(
            journal
                .status(&root.target.tenant, &actual.activation_id)
                .unwrap()
                .unwrap()
                .final_consumption,
            Some(consumption.clone())
        );
        assert!(!format!("{page:?}").contains("private"));
        assert!(
            !journal
                .inspect_tree(&TenantId("foreign".into()), &actual.activation_id, 0, None)
                .unwrap()
                .history_available
        );
    }
    parent.finish(outcome());
}

#[test]
fn caught_provider_observation_is_bounded_scoped_and_never_certifies_terminal_cause() {
    use latent_core::diagnostic::ActivationDiagnosticSink;
    let (journal, _) = journal(2, 2);
    let envelope = envelope("observed");
    let owner = journal.begin(&envelope).unwrap();
    let diagnostic =
        ActivationDiagnostic::new(DiagnosticStage::Provider, DiagnosticReason::ProviderTimeout);
    let before = journal.snapshot().retained_bytes;
    journal.record(
        &TenantId("foreign".into()),
        &envelope.activation_id,
        diagnostic.clone(),
    );
    assert!(journal
        .inspect_tree(&envelope.target.tenant, &envelope.activation_id, 0, None)
        .unwrap()
        .nodes[0]
        .diagnostic
        .is_none());
    for _ in 0..100 {
        journal.record(
            &envelope.target.tenant,
            &envelope.activation_id,
            diagnostic.clone(),
        );
    }
    assert_eq!(journal.snapshot().retained_bytes, before);
    owner.finish(outcome());
    let node = journal
        .inspect_tree(&envelope.target.tenant, &envelope.activation_id, 0, None)
        .unwrap()
        .nodes
        .remove(0);
    assert_eq!(node.diagnostic, Some(diagnostic));
    assert!(!node.diagnostic_is_terminal);
    assert_eq!(
        node.terminal_state,
        Some(ActivationTerminalState::Completed)
    );
}

#[test]
fn cursor_freezes_membership_and_is_bound_to_tenant_anchor_and_journal() {
    let (journal, _) = journal(6, 6);
    let root = envelope("parent");
    let parent = journal.begin(&root).unwrap();
    journal
        .begin(&child("first", "parent", "parent"))
        .unwrap()
        .finish(outcome());
    let first = journal
        .inspect_tree(&root.target.tenant, &root.activation_id, 1, None)
        .unwrap();
    let token = first.next_page_token.unwrap();
    journal
        .begin(&child("later", "parent", "parent"))
        .unwrap()
        .finish(outcome());
    let second = journal
        .inspect_tree(&root.target.tenant, &root.activation_id, 1, Some(&token))
        .unwrap();
    assert_eq!(second.nodes.len(), 1);
    assert_eq!(second.nodes[0].activation_id.0, "first");
    assert!(second.next_page_token.is_none());
    let denied = journal
        .inspect_tree(
            &TenantId("other".into()),
            &root.activation_id,
            1,
            Some(&token),
        )
        .unwrap();
    assert!(!denied.history_available);
    assert!(denied.nodes.is_empty());
    assert!(journal
        .inspect_tree(
            &root.target.tenant,
            &ActivationId("first".into()),
            1,
            Some(&token)
        )
        .is_err());
    let mut forged = token;
    forged.replace_range(34..35, "z");
    assert!(journal
        .inspect_tree(&root.target.tenant, &root.activation_id, 1, Some(&forged))
        .is_err());
    assert!(journal
        .inspect_tree(&root.target.tenant, &root.activation_id, 129, None)
        .is_err());
    parent.finish(outcome());
}

#[test]
fn retention_removes_index_entries_and_explains_expired_anchor_without_certifying_absence() {
    let (journal, clock) = journal(4, 4);
    let root = envelope("parent");
    let parent = journal.begin(&root).unwrap();
    journal
        .begin(&child("first", "parent", "parent"))
        .unwrap()
        .finish(outcome());
    let page = journal
        .inspect_tree(&root.target.tenant, &root.activation_id, 1, None)
        .unwrap();
    parent.finish(outcome());
    clock.elapse(Duration::from_secs(2));
    let expired = journal
        .inspect_tree(
            &root.target.tenant,
            &root.activation_id,
            1,
            page.next_page_token.as_deref(),
        )
        .unwrap();
    assert!(!expired.history_available);
    assert!(expired.cursor_expired);
    assert!(journal.inner.lock().lineage_order.is_empty());
    assert_eq!(journal.snapshot().retained_bytes, 0);
}

#[test]
fn forged_lineage_and_cross_tenant_parent_reject_before_registration() {
    let (journal, _) = journal(8, 8);
    let parent = journal.begin(&envelope("parent")).unwrap();
    let registrations = AtomicUsize::new(0);
    for mut value in [
        child("bad-root", "parent", "other-root"),
        child("missing-parent", "absent", "parent"),
        child("foreign", "parent", "parent"),
    ] {
        if value.activation_id.0 == "foreign" {
            value.principal.tenant = Some(TenantId("other".into()));
            value.target.tenant = TenantId("other".into());
        }
        let failure = journal
            .begin_with(&value, || {
                registrations.fetch_add(1, Ordering::Relaxed);
                Ok(())
            })
            .err()
            .unwrap();
        assert_eq!(failure.code, PlatformErrorCode::PermissionDenied);
    }
    assert_eq!(registrations.load(Ordering::Relaxed), 0);
    assert_eq!(journal.inner.lock().lineage_order.len(), 1);
    parent.finish(outcome());
}

#[test]
fn concurrent_children_keep_one_bounded_index_entry_per_owned_record() {
    let (journal, _) = journal(20, 20);
    let parent = journal.begin(&envelope("parent")).unwrap();
    std::thread::scope(|scope| {
        for index in 0..16 {
            let journal = &journal;
            scope.spawn(move || {
                journal
                    .begin(&child(&format!("child-{index}"), "parent", "parent"))
                    .unwrap()
                    .finish(outcome());
            });
        }
    });
    assert_eq!(
        journal
            .inspect_tree(
                &TenantId("tenant".into()),
                &ActivationId("parent".into()),
                128,
                None
            )
            .unwrap()
            .nodes
            .len(),
        17
    );
    assert_eq!(journal.inner.lock().lineage_order.len(), 17);
    parent.finish(outcome());
}
