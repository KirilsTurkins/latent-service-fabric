use super::*;
use std::sync::{mpsc, Mutex};
use std::thread::ThreadId;

pub(super) enum Event {
    Paused,
    Complete,
}

struct Pause {
    ordinal: usize,
    deadline: Instant,
    events: mpsc::SyncSender<Event>,
    resume: mpsc::Receiver<()>,
}

struct Plan {
    thread: ThreadId,
    calls: usize,
    pause: Option<Pause>,
    failure: Option<PlatformError>,
}

pub(super) struct ControlledClock {
    current: Mutex<ClockSample>,
    plan: Mutex<Option<Plan>>,
}

pub(super) struct Schedule {
    pub triggered: bool,
    pub owner_advanced: bool,
    pub completed: bool,
    pub calls: usize,
}

impl ControlledClock {
    pub(super) fn new() -> Arc<Self> {
        Arc::new(Self {
            current: Mutex::new(ClockSample::new(1_100_000, Instant::now())),
            plan: Mutex::new(None),
        })
    }

    pub(super) fn advance(&self, elapsed: Duration) {
        let mut sample = self.current.lock().unwrap();
        *sample = ClockSample::new(
            sample.unix_millis() + u64::try_from(elapsed.as_millis()).unwrap(),
            sample.monotonic() + elapsed,
        );
    }

    pub(super) fn rewind_wall(&self) {
        let mut sample = self.current.lock().unwrap();
        *sample = ClockSample::new(sample.unix_millis() - 1, sample.monotonic());
    }

    pub(super) fn fail_next(&self, failure: PlatformError) {
        *self.plan.lock().unwrap() = Some(Plan {
            thread: std::thread::current().id(),
            calls: 0,
            pause: None,
            failure: Some(failure),
        });
    }

    pub(super) fn interleave<T>(
        self: &Arc<Self>,
        authority: &Arc<SupplyChainAuthority>,
        ordinal: usize,
        deadline: Instant,
        observe: impl FnOnce() -> T,
    ) -> (T, Schedule) {
        let (events, observed) = mpsc::sync_channel(2);
        let (release, resume) = mpsc::sync_channel(1);
        *self.plan.lock().unwrap() = Some(Plan {
            thread: std::thread::current().id(),
            calls: 0,
            pause: Some(Pause {
                ordinal,
                deadline,
                events: events.clone(),
                resume,
            }),
            failure: None,
        });
        let clock = Arc::clone(self);
        let authority = Arc::clone(authority);
        let coordinator = std::thread::spawn(move || {
            match observed.recv_timeout(deadline.saturating_duration_since(Instant::now())) {
                Ok(Event::Paused) => {
                    clock.advance(Duration::from_secs(1));
                    // The original owner raises the shared high-water mark.
                    // The paused source then encounters real record_current busy.
                    let advanced = authority.covered_clock().is_ok();
                    let released = release.send(()).is_ok();
                    let complete = matches!(
                        observed.recv_timeout(deadline.saturating_duration_since(Instant::now())),
                        Ok(Event::Complete)
                    );
                    (true, advanced, released && complete)
                }
                Ok(Event::Complete) => (false, false, true),
                Err(_) => (false, false, false),
            }
        });
        let result = observe();
        let sent = events.send(Event::Complete).is_ok();
        let (triggered, owner_advanced, completed) = coordinator.join().unwrap();
        let plan = self.plan.lock().unwrap().take().unwrap();
        (
            result,
            Schedule {
                triggered,
                owner_advanced,
                completed: sent && completed,
                calls: plan.calls,
            },
        )
    }
}

impl ActivationClock for ControlledClock {
    fn sample(&self) -> ClockSample {
        *self.current.lock().unwrap()
    }

    fn monotonic_now(&self) -> Instant {
        self.current.lock().unwrap().monotonic()
    }
}

impl SupplyChainClock for ControlledClock {
    fn now(&self) -> Result<u64, PlatformError> {
        let captured = self.current.lock().unwrap().unix_millis() / 1000;
        let (pause, failure) = {
            let mut plan = self.plan.lock().unwrap();
            match plan.as_mut() {
                Some(plan) if plan.thread == std::thread::current().id() => {
                    plan.calls += 1;
                    let pause = if plan
                        .pause
                        .as_ref()
                        .is_some_and(|pause| pause.ordinal == plan.calls)
                    {
                        plan.pause.take()
                    } else {
                        None
                    };
                    (pause, plan.failure.take())
                }
                _ => (None, None),
            }
        };
        if let Some(pause) = pause {
            let _sent = pause.events.send(Event::Paused);
            let _resumed = pause
                .resume
                .recv_timeout(pause.deadline.saturating_duration_since(Instant::now()));
        }
        failure.map_or(Ok(captured), Err)
    }
}
