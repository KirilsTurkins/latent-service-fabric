use super::*;
use crate::ActivationCancellationRegistry;
use latent_core::{
    ActivationBudget, BudgetProfile, ClockSample, DelegationLimits, EffectiveActivationBudget,
    ResourceBudget,
};
use std::{
    future::Future,
    task::Poll,
    time::{Duration, Instant},
};

#[tokio::test]
async fn actual_owner_signals_wake_linked_children_and_keep_late_provider_charges() {
    for stop in 0..4 {
        let registry = ActivationCancellationRegistry::default();
        let root = registry
            .register(ActivationId("parent".to_owned()))
            .unwrap();
        let child_registration = registry.register(ActivationId("child".to_owned())).unwrap();
        let transport = Arc::new(TransportStop::default());
        let root_control = Arc::new(ActivationControl::new(&root, transport.clone(), true));
        let child_control = Arc::new(ActivationControl::new(
            &child_registration,
            Arc::new(TransportStop::default()),
            true,
        ));
        let sample = ClockSample::new(1000, Instant::now());
        let request = ResourceBudget {
            cpu_fuel: 1000,
            memory_bytes: 10_000,
            wall_time_limit_millis: Some(1000),
            child_calls: 4,
            outbound_requests: 0,
            blob_read_bytes: 0,
            blob_write_bytes: 0,
            state_read_bytes: 0,
            state_write_bytes: 0,
            log_bytes: 10,
            effect_count: 0,
        };
        let grant = EffectiveActivationBudget::admit_profile_at(
            BudgetProfile::Phase3,
            &request,
            &request,
            &request,
            None,
            sample,
        )
        .unwrap();
        let parent = ActivationBudget::with_profile(grant, BudgetProfile::Phase3).unwrap();
        parent
            .enable_descendants(DelegationLimits::default(), root_control)
            .unwrap();
        let child_request = ResourceBudget {
            cpu_fuel: 100,
            memory_bytes: 2_000,
            child_calls: 0,
            ..request.clone()
        };
        let delegation = parent
            .delegate_at(&child_request, &request, &request, None, sample)
            .unwrap();
        let grant = delegation.grant();
        let child = delegation
            .accept(&grant, child_control, sample.monotonic())
            .unwrap();
        let provider = child.accounting().clone();
        let mut waiting = Box::pin(
            provider
                .prepare_descendant_cancellation_at(sample.monotonic())
                .unwrap(),
        );
        assert_eq!(parent.host_memory_bytes(), 0);
        assert!(provider.host_memory_bytes() > 0);
        std::future::poll_fn(|cx| {
            assert!(waiting.as_mut().poll(cx).is_pending());
            Poll::Ready(())
        })
        .await;
        match stop {
            0 => {
                root.handle().cancel("parent cancelled");
            }
            1 => {
                let _ = parent.finalize_at(None, sample.monotonic());
            }
            2 => transport
                .mark(super::super::transport_stop::ActivationTransportInterruption::Disconnected),
            _ => {
                child_registration.handle().cancel("child cancelled");
            }
        }
        tokio::time::timeout(Duration::from_millis(100), waiting.as_mut())
            .await
            .unwrap();
        assert!(provider.descendant_is_cancelled());
        let _ = child.finish(None, sample.monotonic());
        assert_eq!(parent.outstanding_reservations(), 1);
        // Physical watcher storage retires before its parent-ledger charge.
        drop(waiting);
        assert_eq!(provider.host_memory_bytes(), 0);
        drop(provider);
        assert_eq!(parent.outstanding_reservations(), 0);
        assert_eq!(parent.descendant_snapshot().unwrap().live_descendants, 0);
    }
}

#[tokio::test]
async fn owned_production_probes_wake_existing_and_late_waiters() {
    use latent_core::BudgetCancellationProbe;

    for stop in 0..3 {
        let registry = ActivationCancellationRegistry::default();
        let registration = registry
            .register(ActivationId("owned-probe".to_owned()))
            .unwrap();
        let transport = Arc::new(TransportStop::default());
        let control = Arc::new(ActivationControl::new(
            &registration,
            transport.clone(),
            true,
        ));
        let sample = ClockSample::new(1000, Instant::now());
        let request = ResourceBudget {
            cpu_fuel: 1000,
            memory_bytes: 20_000,
            wall_time_limit_millis: Some(60_000),
            child_calls: 0,
            outbound_requests: 0,
            state_read_bytes: 0,
            state_write_bytes: 0,
            blob_read_bytes: 0,
            blob_write_bytes: 0,
            log_bytes: 0,
            effect_count: 0,
        };
        let grant = EffectiveActivationBudget::admit_profile_at(
            BudgetProfile::Phase3,
            &request,
            &request,
            &request,
            None,
            sample,
        )
        .unwrap();
        let budget = ActivationBudget::with_profile(grant, BudgetProfile::Phase3).unwrap();
        let mut early = control.clone().cancelled_owned(&budget).unwrap();
        let mut late = control.clone().cancelled_owned(&budget).unwrap();
        let charged = budget.host_memory_bytes();
        eprintln!("two_production_probe_boxes={charged}");
        assert!(charged > 0);
        std::future::poll_fn(|context| {
            assert!(std::pin::Pin::new(&mut early).poll(context).is_pending());
            Poll::Ready(())
        })
        .await;
        match stop {
            0 => {
                control.mark_terminal();
            }
            1 => {
                registration.handle().cancel("owner cancelled");
            }
            _ => transport
                .mark(super::super::transport_stop::ActivationTransportInterruption::Disconnected),
        }
        tokio::time::timeout(Duration::from_millis(100), &mut early)
            .await
            .unwrap();
        tokio::time::timeout(Duration::from_millis(100), &mut late)
            .await
            .unwrap();
        assert_eq!(budget.host_memory_bytes(), charged);
        drop(early);
        drop(late);
        assert_eq!(budget.host_memory_bytes(), 0);
        assert_eq!(budget.outstanding_reservations(), 0);
    }
}
