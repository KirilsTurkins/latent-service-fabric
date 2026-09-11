use std::future::poll_fn;
use std::pin::Pin;
use std::task::Poll;

use latent_core::{ActivationId, PlatformErrorCode};
use serde_json::json;

use crate::{ActivationScheduler, CellClass};

use super::fixture::{id, Fixture};
use super::input::Settings;
use super::offer::{Offer, Row};
use super::{Clock, Result, Run};

pub(super) fn selected(index: u32, tenants: u32) -> bool {
    matches!((index / tenants) % 8, 0 | 3 | 4 | 7)
}

#[test]
fn cancellation_population_covers_each_tenant_and_head_middle_tail_positions() {
    for tenants in [1, 8] {
        let selected = (0..64)
            .filter(|index| selected(*index, tenants))
            .collect::<Vec<_>>();
        assert_eq!(selected.len(), 32);
        for tenant in 0..tenants {
            let local = selected
                .iter()
                .filter(|index| **index % tenants == tenant)
                .map(|index| index / tenants)
                .collect::<Vec<_>>();
            assert_eq!(local.len(), usize::try_from(32 / tenants).unwrap());
            assert!(local.contains(&0));
            assert!(local.contains(&(64 / tenants - 1)));
            assert!(local.iter().any(|index| index % 8 == 3));
            assert!(local.iter().any(|index| index % 8 == 4));
        }
    }
}

pub(super) async fn execute(
    fixture: &Fixture,
    settings: &Settings,
    clock: Clock,
    run: &mut Run,
) -> Result<()> {
    let mut offers = Vec::with_capacity(68);
    let result = sequence(fixture, settings, clock, run, &mut offers).await;
    // Retain every offered row on failure, including conservative reclamations.
    for offer in offers {
        run.rows.push(offer.finish());
    }
    result
}

async fn sequence<'a>(
    fixture: &'a Fixture,
    settings: &Settings,
    clock: Clock,
    run: &mut Run,
    offers: &mut Vec<Offer<'a>>,
) -> Result<()> {
    run.started = clock.now();
    let chosen = setup(fixture, settings, clock, run, offers).await?;
    cancellation_window(fixture, settings, clock, run, offers, &chosen).await?;
    drain(fixture, clock, run, offers).await
}

async fn setup<'a>(
    fixture: &'a Fixture,
    settings: &Settings,
    clock: Clock,
    run: &mut Run,
    offers: &mut Vec<Offer<'a>>,
) -> Result<Vec<(usize, ActivationId)>> {
    for ordinal in 0..4 {
        let row = Row::new(
            ordinal,
            ordinal % settings.tenants,
            "holder",
            clock.now(),
            clock,
        );
        offers.push(Offer::new(fixture, row, clock));
        poll_fn(|context| offers.last_mut().expect("holder").poll_enqueue(context)).await;
        if offers.last().is_none_or(|offer| offer.assignment.is_none()) {
            return Err("scheduler holder did not acquire cell".into());
        }
    }
    run.checkpoint(fixture, "four-holders", clock)?;
    for index in 0..64 {
        let row = Row::new(
            4 + index,
            index % settings.tenants,
            "queued",
            clock.now(),
            clock,
        );
        offers.push(Offer::new(fixture, row, clock));
    }
    let mut all_pending = true;
    poll_fn(|context| {
        for offer in &mut offers[4..] {
            all_pending &= offer.poll_enqueue(context).is_pending();
        }
        Poll::Ready(())
    })
    .await;
    run.checkpoint(fixture, "queued", clock)?;
    let observed = fixture.scheduler.observations(CellClass::Standard);
    if !all_pending
        || observed.active_leases != 4
        || observed.available != 0
        || observed.queue_depth != 64
        || observed.queued_tenants != settings.tenants
    {
        return Err("scheduler storm did not witness full queue".into());
    }
    let chosen = (0..64)
        .filter(|index| selected(*index, settings.tenants))
        .map(|index| {
            (
                usize::try_from(index + 4).expect("bounded ordinal"),
                id(index + 4),
            )
        })
        .collect::<Vec<_>>();
    if chosen.len() != 32 {
        return Err("scheduler cancellation population".into());
    }
    Ok(chosen)
}

async fn cancellation_window(
    fixture: &Fixture,
    settings: &Settings,
    clock: Clock,
    run: &mut Run,
    offers: &mut [Offer<'_>],
    chosen: &[(usize, ActivationId)],
) -> Result<()> {
    if !fixture
        .scheduler
        .reset_work(CellClass::Standard, settings.counters_enabled)
    {
        return Err("missing scheduler work class".into());
    }
    run.checkpoint(fixture, "cancel-before", clock)?;
    let mut polls = 0_u64;
    let began = clock.now();
    {
        // The same original enqueue futures are polled below the selected frame.
        // No spawned task can move cancellation/removal to an unobserved stack.
        let mut future: Pin<Box<dyn std::future::Future<Output = ()> + '_>> = Box::pin(async {
            for (index, activation_id) in chosen {
                offers[*index].row.cancel_requested = Some(clock.now());
                let result = fixture.scheduler.cancel(activation_id).await;
                offers[*index].row.cancel_finished = Some(clock.now());
                offers[*index].row.cancel_accepted = Some(result.is_ok());
                if let Err(error) = result {
                    offers[*index].row.cancel_error = Some(error);
                }
            }
            poll_fn(|context| {
                let mut settled = true;
                for (index, _) in chosen {
                    settled &= offers[*index].poll_enqueue(context).is_ready();
                }
                if settled {
                    Poll::Ready(())
                } else {
                    Poll::Pending
                }
            })
            .await;
        });
        poll_fn(|context| {
            polls = polls.checked_add(1).expect("bounded frame polling");
            super::measured_cancel_and_settle(&mut future, context)
        })
        .await;
    }
    let finished = clock.now();
    run.frame = json!({
        "symbol":super::FRAME, "polls":polls.to_string(),
        "started_nanos":began.to_string(),"finished_nanos":finished.to_string(),
        "cancel_calls":"32", "settled":chosen.iter().filter(|(index,_)|offers[*index].row.result.is_some()).count().to_string(),
        "scope":"cancel-and-original-enqueue-future-settlement",
    });
    run.checkpoint(fixture, "cancel-after", clock)?;
    fixture.scheduler.reset_work(CellClass::Standard, false);
    if chosen.iter().any(|(index, _)| {
        let row = &offers[*index].row;
        row.cancel_accepted != Some(true)
            || row
                .error
                .as_ref()
                .is_none_or(|error| error.code != PlatformErrorCode::Cancelled)
    }) {
        return Err("scheduler cancellation did not settle all original futures".into());
    }
    let observed = fixture.scheduler.observations(CellClass::Standard);
    if observed.active_leases != 4 || observed.queue_depth != 32 || observed.quarantined != 0 {
        return Err("scheduler cancel conservation".into());
    }
    Ok(())
}

async fn drain(
    fixture: &Fixture,
    clock: Clock,
    run: &mut Run,
    offers: &mut [Offer<'_>],
) -> Result<()> {
    for holder in &mut offers[..4] {
        holder.start_release();
        poll_fn(|context| holder.poll_release(context)).await;
    }
    poll_fn(|context| {
        let mut complete = true;
        for offer in &mut offers[4..] {
            if offer.poll_enqueue(context).is_pending() {
                complete = false;
                continue;
            }
            offer.start_release();
            complete &= offer.poll_release(context).is_ready();
        }
        if complete {
            Poll::Ready(())
        } else {
            Poll::Pending
        }
    })
    .await;
    run.finished = clock.now();
    fixture.idle()?;
    run.checkpoint(fixture, "storm-drained", clock)?;
    if offers
        .iter()
        .filter(|offer| offer.row.outcome == "released")
        .count()
        != 36
    {
        return Err("scheduler storm release population".into());
    }
    Ok(())
}
