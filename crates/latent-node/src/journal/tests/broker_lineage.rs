use super::*;
use crate::journal::lineage::owns_broker_parent;
use latent_core::{ActivationBudget, EffectiveActivationBudget};
use std::time::Duration;

fn budget(value: &ActivationEnvelope, clock: &Clock) -> ActivationBudget {
    ActivationBudget::new(
        EffectiveActivationBudget::admit_at(
            &value.budget,
            &value.budget,
            &value.budget,
            None,
            clock.sample(),
        )
        .unwrap(),
    )
}

#[test]
fn broker_parent_requires_original_live_budget_and_selected_source() {
    let (journal, clock) = journal(2, 2);
    let value = envelope("parent");
    let owner = journal.begin(&value).unwrap();
    let original = budget(&value, &clock);
    {
        let state = journal.inner.lock();
        assert!(!owns_broker_parent(
            &state.records[&value.activation_id],
            (&value.target.tenant, &value.target.service),
            &original,
        ));
    }
    owner.record_grant(&original);
    {
        let state = journal.inner.lock();
        let parent = &state.records[&value.activation_id];
        assert!(owns_broker_parent(
            parent,
            (&value.target.tenant, &value.target.service),
            &original.clone()
        ));
        // Equal limits/deadlines or a matching string ID are never ownership.
        assert!(!owns_broker_parent(
            parent,
            (&value.target.tenant, &value.target.service),
            &budget(&value, &clock)
        ));
        for source in [
            latent_routing::InvocationTarget {
                tenant: TenantId("foreign".into()),
                ..value.target.clone()
            },
            latent_routing::InvocationTarget {
                service: latent_core::ServiceId("foreign".into()),
                ..value.target.clone()
            },
        ] {
            assert!(!owns_broker_parent(
                parent,
                (&source.tenant, &source.service),
                &original
            ));
        }
    }
    owner.finish(outcome());
    let state = journal.inner.lock();
    let terminal = &state.records[&value.activation_id];
    assert!(terminal.active_budget.is_none());
    assert!(!owns_broker_parent(
        terminal,
        (&value.target.tenant, &value.target.service),
        &original
    ));
    assert!(terminal.granted_budget.is_some());
}

#[test]
fn reused_parent_id_cannot_adopt_an_old_broker_budget() {
    let (journal, clock) = journal(2, 2);
    let value = envelope("parent");
    let first = journal.begin(&value).unwrap();
    let old_budget = budget(&value, &clock);
    first.record_grant(&old_budget);
    let old_serial = first.serial();
    first.finish(outcome());
    clock.elapse(Duration::from_secs(2));
    let second = journal.begin(&value).unwrap();
    let current_budget = budget(&value, &clock);
    second.record_grant(&current_budget);
    assert!(second.serial() > old_serial);
    {
        let state = journal.inner.lock();
        let parent = &state.records[&value.activation_id];
        assert!(!owns_broker_parent(
            parent,
            (&value.target.tenant, &value.target.service),
            &old_budget
        ));
        assert!(owns_broker_parent(
            parent,
            (&value.target.tenant, &value.target.service),
            &current_budget
        ));
    }
    second.finish(outcome());
    assert_eq!(journal.snapshot().active, 0);
}
