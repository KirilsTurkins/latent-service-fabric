//! Small deterministic building blocks shared by tests and conformance harnesses.

use std::future::Future;
use std::io;
use std::path::{Component, Path, PathBuf};
use std::pin::pin;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::task::{Context, Poll, Wake, Waker};
use std::thread::{self, Thread};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DeterministicIds {
    prefix: String,
    next: u64,
}

impl DeterministicIds {
    pub fn new(prefix: impl Into<String>) -> Self {
        Self {
            prefix: prefix.into(),
            next: 0,
        }
    }

    pub fn next_id(&mut self) -> String {
        let current = self.next;
        self.next = self
            .next
            .checked_add(1)
            .expect("deterministic identifier sequence exhausted");
        format!("{}-{current:016x}", self.prefix)
    }
}

#[derive(Debug, Clone, Default)]
pub struct ManualClock {
    now_nanos: Arc<AtomicU64>,
}

impl ManualClock {
    pub fn from_nanos(now_nanos: u64) -> Self {
        Self {
            now_nanos: Arc::new(AtomicU64::new(now_nanos)),
        }
    }

    pub fn now_nanos(&self) -> u64 {
        self.now_nanos.load(Ordering::SeqCst)
    }

    pub fn set_nanos(&self, now_nanos: u64) {
        self.now_nanos.store(now_nanos, Ordering::SeqCst);
    }

    pub fn advance_nanos(&self, delta: u64) -> u64 {
        let previous = self
            .now_nanos
            .fetch_update(Ordering::SeqCst, Ordering::SeqCst, |current| {
                current.checked_add(delta)
            })
            .expect("manual clock overflow");
        previous + delta
    }
}

#[derive(Debug)]
pub struct TempWorkspace {
    path: PathBuf,
    remove_on_drop: bool,
}

impl TempWorkspace {
    pub fn create_under(root: impl AsRef<Path>, name: &str) -> io::Result<Self> {
        if !is_single_normal_component(name) {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "temporary workspace name must be one normal path component",
            ));
        }

        let root = root.as_ref();
        std::fs::create_dir_all(root)?;
        let path = root.join(name);
        std::fs::create_dir(&path)?;
        Ok(Self {
            path,
            remove_on_drop: true,
        })
    }

    pub fn path(&self) -> &Path {
        &self.path
    }

    pub fn persist(mut self) -> PathBuf {
        self.remove_on_drop = false;
        self.path.clone()
    }
}

impl Drop for TempWorkspace {
    fn drop(&mut self) {
        if self.remove_on_drop {
            let _ = std::fs::remove_dir_all(&self.path);
        }
    }
}

fn is_single_normal_component(name: &str) -> bool {
    let mut components = Path::new(name).components();
    matches!(
        (components.next(), components.next()),
        (Some(Component::Normal(_)), None)
    )
}

#[derive(Debug)]
struct CurrentThreadWaker(Thread);

impl Wake for CurrentThreadWaker {
    fn wake(self: Arc<Self>) {
        self.0.unpark();
    }

    fn wake_by_ref(self: &Arc<Self>) {
        self.0.unpark();
    }
}

pub fn block_on<F: Future>(future: F) -> F::Output {
    let waker = Waker::from(Arc::new(CurrentThreadWaker(thread::current())));
    let mut context = Context::from_waker(&waker);
    let mut future = pin!(future);

    loop {
        match future.as_mut().poll(&mut context) {
            Poll::Ready(output) => return output,
            Poll::Pending => thread::park(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::{block_on, DeterministicIds, ManualClock, TempWorkspace};
    use std::future::Future;
    use std::pin::Pin;
    use std::task::{Context, Poll};

    #[test]
    fn identifiers_are_repeatable() {
        let mut first = DeterministicIds::new("activation");
        let mut second = DeterministicIds::new("activation");

        assert_eq!(first.next_id(), "activation-0000000000000000");
        assert_eq!(first.next_id(), "activation-0000000000000001");
        assert_eq!(second.next_id(), "activation-0000000000000000");
    }

    #[test]
    fn clock_is_shared_without_wall_time() {
        let clock = ManualClock::from_nanos(10);
        let clone = clock.clone();

        assert_eq!(clock.advance_nanos(5), 15);
        assert_eq!(clone.now_nanos(), 15);
        clone.set_nanos(2);
        assert_eq!(clock.now_nanos(), 2);
    }

    #[test]
    fn workspace_uses_requested_path_and_cleans_up() {
        let parent = tempfile::tempdir().expect("temporary parent");
        let path = parent.path().join("fixture-0001");
        {
            let workspace = TempWorkspace::create_under(parent.path(), "fixture-0001")
                .expect("deterministic workspace");
            assert_eq!(workspace.path(), path);
            assert!(path.is_dir());
        }
        assert!(!path.exists());
    }

    #[test]
    fn workspace_rejects_path_traversal() {
        let parent = tempfile::tempdir().expect("temporary parent");
        assert!(TempWorkspace::create_under(parent.path(), "../escape").is_err());
    }

    #[test]
    fn executor_handles_a_wake_before_parking() {
        assert_eq!(block_on(WakeOnce::default()), 42);
    }

    #[derive(Debug, Default)]
    struct WakeOnce {
        polled: bool,
    }

    impl Future for WakeOnce {
        type Output = u8;

        fn poll(mut self: Pin<&mut Self>, context: &mut Context<'_>) -> Poll<Self::Output> {
            if self.polled {
                Poll::Ready(42)
            } else {
                self.polled = true;
                context.waker().wake_by_ref();
                Poll::Pending
            }
        }
    }
}
