//! Physical payloads precede their original logical owner, including on unwind.
//! Only observed EOF with no pending future or upload can retire synchronously.
pub(crate) struct Retirement<W, U, B, D, O, S> {
    work: Option<W>,
    upload: Option<U>,
    _body: Option<B>,
    _buffers: D,
    _owner: Option<O>,
    _slot: Option<S>,
}
impl<W, U, B, D, O, S> Retirement<W, U, B, D, O, S> {
    pub(crate) fn new(
        work: Option<W>,
        upload: Option<U>,
        body: Option<B>,
        buffers: D,
        owner: Option<O>,
        slot: Option<S>,
    ) -> Self {
        Self {
            work,
            upload,
            _body: body,
            _buffers: buffers,
            _owner: owner,
            _slot: slot,
        }
    }
    pub(crate) fn retire(self, eof: bool, defer: impl FnOnce(Self)) {
        if eof && self.work.is_none() && self.upload.is_none() {
            // Resource-drop is synchronous, unlike cancelling a live canonical
            // future. Any detached provider cleanup retains its own paid owner.
            drop(self);
        } else {
            defer(self);
        }
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    use std::{
        cell::{Cell, RefCell},
        rc::Rc,
    };
    struct Owned {
        name: &'static str,
        live: Rc<Cell<usize>>,
        events: Rc<RefCell<Vec<&'static str>>>,
        panic: bool,
    }
    impl Drop for Owned {
        fn drop(&mut self) {
            assert!(self.live.get() > 0, "resource lost its original owner");
            self.events.borrow_mut().push(self.name);
            if self.name == "owner" {
                self.live.set(self.live.get() - 1);
            }
            assert!(!self.panic, "resource-drop-control");
        }
    }
    fn part(
        name: &'static str,
        live: &Rc<Cell<usize>>,
        events: &Rc<RefCell<Vec<&'static str>>>,
    ) -> Owned {
        Owned {
            name,
            live: live.clone(),
            events: events.clone(),
            panic: false,
        }
    }
    type Pending = Retirement<Owned, Owned, Owned, Owned, Owned, ()>;
    #[test]
    fn completed_eof_retires_resources_before_owner_without_deferring() {
        let live = Rc::new(Cell::new(1));
        let events = Rc::new(RefCell::new(Vec::new()));
        Pending::new(
            None,
            None,
            Some(part("body", &live, &events)),
            part("buffers", &live, &events),
            Some(part("owner", &live, &events)),
            Some(()),
        )
        .retire(true, |_| {
            panic!("completed EOF must not retain its Task until root drain")
        });
        assert_eq!(live.get(), 0);
        assert_eq!(*events.borrow(), ["body", "buffers", "owner"]);
    }
    #[test]
    fn sequential_completed_requests_reuse_the_original_finite_owner_capacity() {
        let live = Rc::new(Cell::new(5)); // Five unrelated admitted Tasks.
        let events = Rc::new(RefCell::new(Vec::new()));
        live.set(live.get() + 1);
        let held = Pending::new(
            Some(part("held-work", &live, &events)),
            None,
            None,
            part("held-buffers", &live, &events),
            Some(part("owner", &live, &events)),
            Some(()),
        );
        for _ in 0..32 {
            assert!(
                live.get() < 8,
                "original Task ceiling must admit the next sibling"
            );
            live.set(live.get() + 1);
            Pending::new(
                None,
                None,
                Some(part("body", &live, &events)),
                part("buffers", &live, &events),
                Some(part("owner", &live, &events)),
                Some(()),
            )
            .retire(true, |_| panic!("settled sibling was retained"));
            assert_eq!(live.get(), 6);
        }
        let mut deferred = None;
        held.retire(false, |value| deferred = Some(value));
        assert_eq!(live.get(), 6);
        assert!(!events.borrow().contains(&"held-work"));
        drop(deferred);
        assert_eq!(live.get(), 5);
    }
    #[test]
    fn pending_future_upload_or_missing_eof_cannot_take_the_early_path() {
        for (eof, work, upload) in [
            (false, false, false),
            (false, true, false),
            (true, true, false),
            (true, false, true),
        ] {
            let live = Rc::new(Cell::new(1));
            let events = Rc::new(RefCell::new(Vec::new()));
            let mut deferred = None;
            Pending::new(
                work.then(|| part("future", &live, &events)),
                upload.then(|| part("upload", &live, &events)),
                Some(part("body", &live, &events)),
                part("buffers", &live, &events),
                Some(part("owner", &live, &events)),
                Some(()),
            )
            .retire(eof, |value| deferred = Some(value));
            assert!(deferred.is_some());
            assert!(events.borrow().is_empty());
            assert_eq!(live.get(), 1);
            drop(deferred);
            assert_eq!(live.get(), 0);
            let expected: Vec<_> = work
                .then_some("future")
                .into_iter()
                .chain(upload.then_some("upload"))
                .chain(["body", "buffers", "owner"])
                .collect();
            assert_eq!(*events.borrow(), expected);
        }
    }
    #[test]
    fn original_owner_survives_resource_destructor_unwind() {
        for eof in [false, true] {
            let live = Rc::new(Cell::new(1));
            let events = Rc::new(RefCell::new(Vec::new()));
            let mut body = part("body", &live, &events);
            body.panic = true;
            let retirement = Pending::new(
                None,
                None,
                Some(body),
                part("buffers", &live, &events),
                Some(part("owner", &live, &events)),
                Some(()),
            );
            let outcome = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                retirement.retire(eof, drop)
            }));
            assert!(outcome.is_err());
            assert_eq!(*events.borrow(), ["body", "buffers", "owner"]);
            assert_eq!(live.get(), 0);
        }
    }
}
