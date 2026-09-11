use std::future::Future;
use std::pin::Pin;
use std::task::{Context, Poll};
use std::time::Duration;

use latent_core::{BoxFuture, PlatformError};

use crate::{ActivationScheduler, AdmittedSchedulingRequest, ScheduledActivation};

use super::fixture::{Cancellation, Fixture};
use super::Clock;

pub(super) struct Row {
    pub ordinal: u32,
    pub tenant: u32,
    pub role: &'static str,
    pub scheduled: u64,
    pub dispatched: u64,
    pub admission_started: Option<u64>,
    pub admission_finished: Option<u64>,
    pub admitted: Option<u64>,
    pub deadline: Option<u64>,
    pub deadline_unix_millis: Option<u64>,
    pub enqueue_called: Option<u64>,
    pub result: Option<u64>,
    pub release_started: Option<u64>,
    pub released: Option<u64>,
    pub cancel_requested: Option<u64>,
    pub cancel_finished: Option<u64>,
    pub cancel_accepted: Option<bool>,
    pub cancel_error: Option<PlatformError>,
    pub outcome: &'static str,
    pub error: Option<PlatformError>,
    pub cleanup_reclaimed: bool,
}

impl Row {
    pub fn new(
        ordinal: u32,
        tenant: u32,
        role: &'static str,
        scheduled: u64,
        clock: Clock,
    ) -> Self {
        Self {
            ordinal,
            tenant,
            role,
            scheduled,
            dispatched: clock.now(),
            admission_started: None,
            admission_finished: None,
            admitted: None,
            deadline: None,
            deadline_unix_millis: None,
            enqueue_called: None,
            result: None,
            release_started: None,
            released: None,
            cancel_requested: None,
            cancel_finished: None,
            cancel_accepted: None,
            cancel_error: None,
            outcome: "pending",
            error: None,
            cleanup_reclaimed: false,
        }
    }
}

type ReleaseFuture = Pin<Box<dyn Future<Output = std::result::Result<(), PlatformError>>>>;

pub(super) struct Offer<'a> {
    pub row: Row,
    pending: Option<BoxFuture<'a, std::result::Result<ScheduledActivation, PlatformError>>>,
    pub assignment: Option<ScheduledActivation>,
    hold: Option<Pin<Box<tokio::time::Sleep>>>,
    release: Option<ReleaseFuture>,
    clock: Clock,
}

impl<'a> Offer<'a> {
    pub fn new(fixture: &'a Fixture, mut row: Row, clock: Clock) -> Self {
        row.admission_started = Some(clock.now());
        let result = fixture.admit(row.ordinal, row.tenant);
        row.admission_finished = Some(clock.now());
        let pending = match result {
            Ok(permit) => {
                row.admitted = row.admission_finished;
                row.deadline = permit
                    .deadline()
                    .monotonic()
                    .map(|value| clock.offset(value));
                row.deadline_unix_millis = permit.deadline().unix_millis();
                let request = AdmittedSchedulingRequest {
                    cancellation: Cancellation::new(row.ordinal),
                    permit,
                };
                row.enqueue_called = Some(clock.now());
                Some(fixture.scheduler.enqueue(request))
            }
            Err(error) => {
                row.outcome = "admission-error";
                row.error = Some(error);
                None
            }
        };
        Self {
            row,
            pending,
            assignment: None,
            hold: None,
            release: None,
            clock,
        }
    }

    pub fn poll_enqueue(&mut self, context: &mut Context<'_>) -> Poll<()> {
        let Some(future) = &mut self.pending else {
            return Poll::Ready(());
        };
        let Poll::Ready(result) = future.as_mut().poll(context) else {
            return Poll::Pending;
        };
        self.row.result = Some(self.clock.now());
        drop(self.pending.take());
        match result {
            Ok(assignment) => {
                self.row.outcome = "assigned";
                self.assignment = Some(assignment);
            }
            Err(error) => {
                self.row.outcome = "scheduler-error";
                self.row.error = Some(error);
            }
        }
        Poll::Ready(())
    }

    pub fn start_release(&mut self) {
        if let Some(assignment) = self.assignment.take() {
            self.row.release_started = Some(self.clock.now());
            self.release = Some(Box::pin(assignment.release()));
        }
    }

    pub fn poll_release(&mut self, context: &mut Context<'_>) -> Poll<()> {
        let Some(future) = &mut self.release else {
            return Poll::Ready(());
        };
        let Poll::Ready(result) = future.as_mut().poll(context) else {
            return Poll::Pending;
        };
        let finished = self.clock.now();
        drop(self.release.take());
        match result {
            Ok(()) => {
                self.row.released = Some(finished);
                self.row.outcome = "released";
            }
            Err(error) => {
                self.row.outcome = "release-error";
                self.row.error = Some(error);
            }
        }
        Poll::Ready(())
    }

    pub fn poll_load(&mut self, context: &mut Context<'_>) -> Poll<()> {
        if self.poll_enqueue(context).is_pending() {
            return Poll::Pending;
        }
        if self.assignment.is_some() {
            let hold = self
                .hold
                .get_or_insert_with(|| Box::pin(tokio::time::sleep(Duration::from_millis(10))));
            if hold.as_mut().poll(context).is_pending() {
                return Poll::Pending;
            }
            drop(self.hold.take());
            self.start_release();
        }
        self.poll_release(context)
    }

    pub fn finish(mut self) -> Row {
        self.cleanup();
        std::mem::replace(&mut self.row, Row::new(0, 0, "unused", 0, self.clock))
    }

    fn cleanup(&mut self) {
        drop(self.pending.take());
        drop(self.release.take());
        if let Some(assignment) = self.assignment.take() {
            // These diagnostic assignments never enter an execution backend.
            assignment.reclaim_before_execution();
            self.row.cleanup_reclaimed = true;
        }
    }
}

impl Drop for Offer<'_> {
    fn drop(&mut self) {
        self.cleanup();
    }
}
