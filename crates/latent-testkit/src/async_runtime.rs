//! Explicit single-threaded async execution for tests.

use std::future::Future;
use std::io;

/// A current-thread Tokio runtime owned by a test harness.
///
/// Construction is explicit and never happens as part of a service definition.
/// It creates no worker-thread pool and is intended only for tests that require
/// Tokio timers or task scheduling beyond [`crate::block_on`].
pub struct AsyncTestRuntime {
    runtime: tokio::runtime::Runtime,
}

impl AsyncTestRuntime {
    pub fn new() -> io::Result<Self> {
        tokio::runtime::Builder::new_current_thread()
            .enable_time()
            .build()
            .map(|runtime| Self { runtime })
    }

    pub fn block_on<F: Future>(&self, future: F) -> F::Output {
        self.runtime.block_on(future)
    }
}

#[cfg(test)]
mod tests {
    use super::AsyncTestRuntime;

    #[test]
    fn executes_on_an_explicit_current_thread_runtime() {
        let runtime = AsyncTestRuntime::new().expect("current-thread test runtime");
        let value = runtime.block_on(async {
            tokio::task::yield_now().await;
            42
        });
        assert_eq!(value, 42);
    }
}
