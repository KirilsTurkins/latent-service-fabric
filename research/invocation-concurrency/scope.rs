//! Research-only, stackless, bounded join. Not a thread or runtime replacement.
use std::future::{poll_fn, Future};
use std::pin::Pin;
use std::task::{Context, Poll};

pub const MAX_TASKS: usize = 8;
pub const TASK_LIMIT: u32 = 900;
pub type Task<'a> = Pin<Box<dyn Future<Output = Result<u32, u32>> + 'a>>;

/// One poll per live child per round; rotate which child is polled first.
/// Return results in spawn order, including errors, only after all children exit.
/// Dropping this future drops every remaining child, but does not certify that
/// a dispatched external effect was undone or a provider physically retired.
pub async fn join<'a>(mut tasks: Vec<Task<'a>>) -> Result<Vec<Result<u32, u32>>, u32> {
    if tasks.len() > MAX_TASKS {
        return Err(TASK_LIMIT);
    }
    let count = tasks.len();
    let mut results = vec![None; count];
    let mut first = 0;
    poll_fn(move |cx| {
        for offset in 0..count {
            let index = (first + offset) % count;
            if results[index].is_none() {
                if let Poll::Ready(value) = tasks[index].as_mut().poll(cx) {
                    results[index] = Some(value);
                }
            }
        }
        if count != 0 {
            first = (first + 1) % count;
        }
        if results.iter().all(Option::is_some) {
            Poll::Ready(Ok(results.iter().map(|value| value.unwrap()).collect()))
        } else {
            // Do not busy-poll. Pending children own their wake registrations.
            Poll::Pending
        }
    })
    .await
}

/// A finite cooperative checkpoint for the CPU comparison and rendezvous probe.
#[derive(Default)]
pub struct YieldOnce(bool);

impl Future for YieldOnce {
    type Output = ();
    fn poll(mut self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<()> {
        if self.0 {
            Poll::Ready(())
        } else {
            self.0 = true;
            cx.waker().wake_by_ref();
            Poll::Pending
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::cell::RefCell;
    use std::rc::Rc;
    use std::sync::Arc;
    use std::task::{Wake, Waker};

    struct Noop;
    impl Wake for Noop {
        fn wake(self: Arc<Self>) {}
    }
    struct Probe {
        id: u32,
        polled: bool,
        log: Rc<RefCell<Vec<u32>>>,
        drops: Rc<Cell<usize>>,
    }
    use std::cell::Cell;
    impl Future for Probe {
        type Output = Result<u32, u32>;
        fn poll(mut self: Pin<&mut Self>, _: &mut Context<'_>) -> Poll<Self::Output> {
            self.log.borrow_mut().push(self.id);
            if self.polled {
                Poll::Ready(if self.id == 1 { Err(7) } else { Ok(self.id) })
            } else {
                self.polled = true;
                Poll::Pending
            }
        }
    }
    impl Drop for Probe {
        fn drop(&mut self) {
            self.drops.set(self.drops.get() + 1);
        }
    }
    fn tasks(
        count: u32,
        log: &Rc<RefCell<Vec<u32>>>,
        drops: &Rc<Cell<usize>>,
    ) -> Vec<Task<'static>> {
        (0..count)
            .map(|id| {
                Box::pin(Probe {
                    id,
                    polled: false,
                    log: log.clone(),
                    drops: drops.clone(),
                }) as Task<'static>
            })
            .collect()
    }
    #[test]
    fn round_robin_preserves_results_and_errors_in_spawn_order() {
        let log = Rc::new(RefCell::new(Vec::new()));
        let drops = Rc::new(Cell::new(0));
        let mut join = Box::pin(join(tasks(3, &log, &drops)));
        let waker = Waker::from(Arc::new(Noop));
        let mut cx = Context::from_waker(&waker);
        assert!(join.as_mut().poll(&mut cx).is_pending());
        assert_eq!(*log.borrow(), vec![0, 1, 2]);
        assert_eq!(
            join.as_mut().poll(&mut cx),
            Poll::Ready(Ok(vec![Ok(0), Err(7), Ok(2)]))
        );
        assert_eq!(*log.borrow(), vec![0, 1, 2, 1, 2, 0]);
        drop(join);
        assert_eq!(drops.get(), 3);
    }
    #[test]
    fn dropping_parent_drops_all_pending_children() {
        let log = Rc::new(RefCell::new(Vec::new()));
        let drops = Rc::new(Cell::new(0));
        let mut join = Box::pin(join(tasks(8, &log, &drops)));
        let waker = Waker::from(Arc::new(Noop));
        assert!(join
            .as_mut()
            .poll(&mut Context::from_waker(&waker))
            .is_pending());
        assert_eq!(drops.get(), 0);
        drop(join);
        assert_eq!(drops.get(), 8);
    }
    #[test]
    fn too_many_children_never_poll_and_are_all_dropped() {
        let log = Rc::new(RefCell::new(Vec::new()));
        let drops = Rc::new(Cell::new(0));
        let mut join = Box::pin(join(tasks(9, &log, &drops)));
        let waker = Waker::from(Arc::new(Noop));
        assert_eq!(
            join.as_mut().poll(&mut Context::from_waker(&waker)),
            Poll::Ready(Err(TASK_LIMIT))
        );
        drop(join);
        assert!(log.borrow().is_empty());
        assert_eq!(drops.get(), 9);
    }
    #[test]
    fn empty_scope_returns_without_a_wake() {
        let mut join = Box::pin(join(Vec::new()));
        let waker = Waker::from(Arc::new(Noop));
        assert_eq!(
            join.as_mut().poll(&mut Context::from_waker(&waker)),
            Poll::Ready(Ok(Vec::new()))
        );
    }
}
