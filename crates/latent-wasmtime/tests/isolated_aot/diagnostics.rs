//! Bounded test diagnostics, never a success or sandbox receipt cache.
use std::cell::Cell;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::time::Instant;

thread_local! {
    static CASE: Cell<&'static str> = const { Cell::new("") };
}
static EVENTS: AtomicUsize = AtomicUsize::new(0);
const MAX_EVENTS: usize = 4096;

pub struct Span {
    stage: &'static str,
    started: Instant,
    enabled: bool,
}
impl Span {
    pub fn new(stage: &'static str) -> Self {
        let enabled = std::env::var_os("LSF_AOT_TEST_TIMINGS").is_some();
        let span = Self {
            stage,
            started: Instant::now(),
            enabled,
        };
        // Start markers also identify the active stage in ordinary failing tests.
        span.emit("started");
        span
    }
    fn emit(&self, outcome: &str) {
        if EVENTS.fetch_add(1, Ordering::Relaxed) >= MAX_EVENTS {
            return;
        }
        let thread = std::thread::current();
        let case = CASE.with(Cell::get);
        let case = if case.is_empty() {
            thread.name().unwrap_or("unnamed")
        } else {
            case
        };
        let case: String = case.chars().take(160).collect();
        eprintln!(
            "LSF_AOT_STAGE {}",
            serde_json::json!({
                "case": case, "stage": self.stage, "outcome": outcome,
                "elapsed_ns": self.started.elapsed().as_nanos(),
            })
        );
    }
}
impl Drop for Span {
    fn drop(&mut self) {
        if std::thread::panicking() {
            self.emit("panicked");
        } else if self.enabled {
            self.emit("completed");
        }
    }
}

pub fn case(name: &'static str, run: impl FnOnce()) {
    struct CaseGuard(&'static str);
    impl Drop for CaseGuard {
        fn drop(&mut self) {
            CASE.with(|case| case.set(self.0));
        }
    }
    let _guard = CaseGuard(CASE.with(|case| case.replace(name)));
    eprintln!("LSF_AOT_CASE started {name}");
    let _stage = Span::new("scenario");
    run();
    eprintln!("LSF_AOT_CASE passed {name}");
}
