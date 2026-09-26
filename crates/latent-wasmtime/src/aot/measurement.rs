//! Opt-in bounded parent-side observations, never cached authorization evidence.
//! Worker environment, protocol, sandbox and diagnostic budget stay unchanged.
#[cfg(feature = "aot-test-timings")]
use std::{
    sync::atomic::{AtomicUsize, Ordering},
    time::Instant,
};

pub(super) struct Span {
    #[cfg(feature = "aot-test-timings")]
    observation: Option<(&'static str, Instant)>,
}
impl Span {
    pub(super) fn new(_stage: &'static str) -> Self {
        Self {
            #[cfg(feature = "aot-test-timings")]
            observation: std::env::var_os("LSF_AOT_TEST_TIMINGS").map(|_| (_stage, Instant::now())),
        }
    }
}
#[cfg(feature = "aot-test-timings")]
impl Drop for Span {
    fn drop(&mut self) {
        static EVENTS: AtomicUsize = AtomicUsize::new(0);
        if let Some((stage, started)) = self.observation {
            if EVENTS.fetch_add(1, Ordering::Relaxed) < 4096 {
                // Fixed stage names only: no paths, digests, input, key or child output.
                eprintln!(
                    "LSF_AOT_MEASURE {{\"stage\":\"{stage}\",\"elapsed_ns\":{}}}",
                    started.elapsed().as_nanos()
                );
            }
        }
    }
}
