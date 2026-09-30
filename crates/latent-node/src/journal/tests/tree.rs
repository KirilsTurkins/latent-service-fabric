use super::*;
use latent_core::diagnostic::{ActivationDiagnostic, DiagnosticReason, DiagnosticStage};

fn child(id: &str, parent: &str, root: &str) -> ActivationEnvelope {
    let mut value = envelope(id);
    value.parent_activation_id = Some(ActivationId(parent.into()));
    value.root_activation_id = ActivationId(root.into());
    value
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
