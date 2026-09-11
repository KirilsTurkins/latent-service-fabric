use std::future::{poll_fn, Future};
use std::task::Context;

use super::fixture::Fixture;
use super::input::Settings;
use super::offer::{Offer, Row};
use super::{Clock, Result, Run};

fn drain(active: &mut Vec<Offer<'_>>, completed: &mut Vec<Row>, context: &mut Context<'_>) {
    let mut index = 0;
    while index < active.len() {
        if active[index].poll_load(context).is_ready() {
            completed.push(active.swap_remove(index).finish());
        } else {
            index += 1;
        }
    }
}

pub(super) async fn execute(
    fixture: &Fixture,
    settings: &Settings,
    clock: Clock,
    run: &mut Run,
) -> Result<()> {
    for ordinal in 0..settings.warmup_offers {
        let row = Row::new(
            ordinal,
            ordinal % settings.tenants,
            "warmup",
            clock.now(),
            clock,
        );
        let mut offer = Offer::new(fixture, row, clock);
        poll_fn(|context| offer.poll_load(context)).await;
        run.rows.push(offer.finish());
        if run.rows.last().is_none_or(|row| row.outcome != "released") {
            return Err("scheduler warmup failed".into());
        }
    }
    fixture.idle()?;
    run.checkpoint(fixture, "after-warmup", clock)?;
    run.started = clock.now();
    let mut active = Vec::with_capacity(usize::try_from(settings.pending_capacity)?);
    for index in 0..settings.measured_offers {
        if settings.rate_per_second == 0 {
            poll_fn(|context| {
                drain(&mut active, &mut run.rows, context);
                if active.is_empty() {
                    std::task::Poll::Ready(())
                } else {
                    std::task::Poll::Pending
                }
            })
            .await;
        }
        let scheduled = if settings.rate_per_second == 0 {
            clock.now()
        } else {
            run.started + u64::from(index) * 1_000_000_000 / u64::from(settings.rate_per_second)
        };
        let mut timer = Box::pin(tokio::time::sleep_until(clock.at(scheduled).into()));
        poll_fn(|context| {
            drain(&mut active, &mut run.rows, context);
            if settings.rate_per_second == 0 {
                if active.is_empty() {
                    return std::task::Poll::Ready(());
                }
            } else if timer.as_mut().poll(context).is_ready() {
                return std::task::Poll::Ready(());
            }
            std::task::Poll::Pending
        })
        .await;
        let mut row = Row::new(
            settings.warmup_offers + index,
            index % settings.tenants,
            "measured",
            scheduled,
            clock,
        );
        if active.len() == usize::try_from(settings.pending_capacity)? {
            row.outcome = "backpressure";
            run.rows.push(row);
        } else {
            active.push(Offer::new(fixture, row, clock));
        }
        if index % 32 == 31 {
            run.checkpoint(fixture, &format!("load-{index:05}"), clock)?;
        }
    }
    poll_fn(|context| {
        drain(&mut active, &mut run.rows, context);
        if active.is_empty() {
            std::task::Poll::Ready(())
        } else {
            std::task::Poll::Pending
        }
    })
    .await;
    run.finished = clock.now();
    fixture.idle()?;
    run.checkpoint(fixture, "load-finished", clock)?;
    Ok(())
}
