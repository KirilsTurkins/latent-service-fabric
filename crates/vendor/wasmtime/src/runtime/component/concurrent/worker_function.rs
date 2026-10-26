//! Pre-admit the exact completion closure before the initial host poll.
//!
//! The continuation reserves first; this typed factory then reserves its output
//! without running it. The original owner stays outside the one-shot Box.

use crate::runtime::native_memory::{self, Memory};
use crate::vm::VMStore;
use crate::{NativeAllocation, Result};
use alloc::boxed::Box;
use core::alloc::Layout;
use core::marker::PhantomData;
use core::mem::ManuallyDrop;

type BoxedFunction = Box<dyn FnOnce(&mut dyn VMStore) -> Result<()> + Send>;

pub(super) struct PreparedWorker<Context, Value, Factory, Function> {
    context: Context,
    factory: Factory,
    allocation: Option<Box<dyn NativeAllocation>>,
    admitted: bool,
    _output: PhantomData<fn(Value) -> Function>,
}

impl<Context, Value, Factory, Function> PreparedWorker<Context, Value, Factory, Function>
where
    Factory: FnOnce(Context, Value) -> Function,
    Function: FnOnce(&mut dyn VMStore) -> Result<()> + Send + 'static,
{
    pub(super) fn new(context: Context, factory: Factory) -> Self {
        // Deliberately no reservation here: the enclosing pending-output Box
        // must remain admission #4, before this closure's admission #5.
        Self {
            context,
            factory,
            allocation: None,
            admitted: false,
            _output: PhantomData,
        }
    }

    pub(super) fn admit(&mut self, memory: &Memory) -> Result<()> {
        assert!(!self.admitted);
        self.allocation = native_memory::reserve(memory, Layout::new::<Function>().size())?;
        self.admitted = true;
        Ok(())
    }

    pub(super) fn into_context(self) -> Context {
        assert!(self.admitted);
        let Self {
            context,
            factory,
            allocation,
            ..
        } = self;
        // Ready never creates a completion closure Box. Refund this unused,
        // unconfirmed reservation before the original direct lower call.
        drop(factory);
        drop(allocation);
        context
    }

    pub(super) fn finish(self, value: Value) -> WorkerFunction {
        assert!(self.admitted);
        let Self {
            context,
            factory,
            allocation,
            ..
        } = self;
        // SAME output type and reservation; no post-I/O admission or second
        // heap wrapper. Coercion adds pointer metadata, not another allocation.
        let function: BoxedFunction = Box::new(factory(context, value));
        let Some(allocation) = allocation else {
            return WorkerFunction::legacy(function);
        };
        let mut owner = AccountedFunction {
            function: ManuallyDrop::new(Some(function)),
            allocation: ManuallyDrop::new(allocation),
            invoking: false,
        };
        owner.allocation.allocated();
        WorkerFunction(Kind::Accounted(owner))
    }
}

pub(super) struct WorkerFunction(Kind);

enum Kind {
    Legacy(BoxedFunction),
    Accounted(AccountedFunction),
}

struct AccountedFunction {
    function: ManuallyDrop<Option<BoxedFunction>>,
    allocation: ManuallyDrop<Box<dyn NativeAllocation>>,
    invoking: bool,
}

impl WorkerFunction {
    // Adapt an existing Box without another allocation or fallible admission.
    // The separate stream callback remains outside the paid first_poll slice.
    pub(super) fn legacy(function: BoxedFunction) -> Self {
        Self(Kind::Legacy(function))
    }

    pub(super) fn invoke(self, store: &mut dyn VMStore) -> Result<()> {
        match self.0 {
            Kind::Legacy(function) => function(store),
            Kind::Accounted(owner) => owner.invoke(store),
        }
    }
}

impl AccountedFunction {
    fn invoke(mut self, store: &mut dyn VMStore) -> Result<()> {
        // Existing Box<dyn FnOnce> consumes its one-shot target. Keep the
        // outside owner through the complete call and Box deallocation.
        self.invoking = true;
        let function = self.function.take().expect("private worker consumed once");
        let result = function(store);
        self.invoking = false;
        result
    }
}

impl Drop for AccountedFunction {
    fn drop(&mut self) {
        // SAFETY: private affine fields are destroyed once. Unrun queue drops
        // destroy/deallocate the function first. A normal invocation consumed
        // the Box before this refund. Either function-destructor or call unwind
        // conservatively retains the SAME original charge, never a new ledger.
        unsafe {
            ManuallyDrop::drop(&mut self.function);
            if !self.invoking {
                ManuallyDrop::drop(&mut self.allocation);
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{AsContextMut, Engine, Store};
    use alloc::sync::Arc;
    use core::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
    use std::panic::{AssertUnwindSafe, catch_unwind};

    #[derive(Default)]
    struct Probe {
        requests: AtomicUsize,
        live: AtomicUsize,
        factories: AtomicUsize,
        confirmations: AtomicUsize,
        invocations: AtomicUsize,
        context_dropped: AtomicBool,
        owner_dropped: AtomicBool,
    }
    struct TestContext {
        probe: Arc<Probe>,
        panic_call: bool,
        panic_drop: bool,
        selected: bool,
    }
    impl TestContext {
        fn invoke(self, value: u32) -> Result<()> {
            self.probe.invocations.fetch_add(1, Ordering::SeqCst);
            assert_eq!(value, 42);
            assert!(!self.probe.context_dropped.load(Ordering::SeqCst));
            if self.selected {
                assert_eq!(self.probe.live.load(Ordering::SeqCst), 1);
            }
            assert!(!self.panic_call, "worker-call-control");
            Ok(())
        }
    }
    impl Drop for TestContext {
        fn drop(&mut self) {
            if self.selected && self.probe.factories.load(Ordering::SeqCst) != 0 {
                assert_eq!(self.probe.live.load(Ordering::SeqCst), 1);
                assert!(!self.probe.owner_dropped.load(Ordering::SeqCst));
            }
            self.probe.context_dropped.store(true, Ordering::SeqCst);
            assert!(!self.panic_drop, "worker-destructor-control");
        }
    }
    fn factory(
        context: TestContext,
        value: u32,
    ) -> impl FnOnce(&mut dyn VMStore) -> Result<()> + Send {
        context.probe.factories.fetch_add(1, Ordering::SeqCst);
        move |_: &mut dyn VMStore| context.invoke(value)
    }
    fn context(
        probe: &Arc<Probe>,
        panic_call: bool,
        panic_drop: bool,
        selected: bool,
    ) -> TestContext {
        TestContext {
            probe: probe.clone(),
            panic_call,
            panic_drop,
            selected,
        }
    }
    struct Owner {
        probe: Arc<Probe>,
        panic_confirmation: bool,
    }
    impl NativeAllocation for Owner {
        fn allocated(&mut self) {
            self.probe.confirmations.fetch_add(1, Ordering::SeqCst);
            assert!(!self.panic_confirmation, "worker-confirmation-control");
        }
    }
    impl Drop for Owner {
        fn drop(&mut self) {
            if self.probe.factories.load(Ordering::SeqCst) != 0 {
                assert!(self.probe.context_dropped.load(Ordering::SeqCst));
            } else {
                assert_eq!(self.probe.confirmations.load(Ordering::SeqCst), 0);
            }
            assert_eq!(self.probe.live.fetch_sub(1, Ordering::SeqCst), 1);
            assert!(!self.probe.owner_dropped.swap(true, Ordering::SeqCst));
        }
    }
    struct Memory {
        probe: Arc<Probe>,
        expected: usize,
        refuse: bool,
        panic_confirmation: bool,
    }
    impl crate::NativeMemory for Memory {
        fn reserve(&self, bytes: usize) -> Result<Box<dyn NativeAllocation>> {
            assert_eq!(bytes, self.expected);
            self.probe.requests.fetch_add(1, Ordering::SeqCst);
            if self.refuse {
                crate::bail!("original-worker-refusal-control");
            }
            assert_eq!(self.probe.live.fetch_add(1, Ordering::SeqCst), 0);
            Ok(Box::new(Owner {
                probe: self.probe.clone(),
                panic_confirmation: self.panic_confirmation,
            }))
        }
    }
    fn memory<Factory, Function>(
        probe: &Arc<Probe>,
        _: &Factory,
        refuse: bool,
        panic_confirmation: bool,
    ) -> native_memory::Memory
    where
        Factory: FnOnce(TestContext, u32) -> Function,
    {
        Some(Arc::new(Memory {
            probe: probe.clone(),
            expected: Layout::new::<Function>().size(),
            refuse,
            panic_confirmation,
        }))
    }
    fn invoke(function: WorkerFunction) -> Result<()> {
        // Harness only: no component compilation or new activation ledger.
        let mut store = Store::new(&Engine::default(), ());
        function.invoke(store.as_context_mut().0)
    }

    #[test]
    fn worker_function_refuses_before_factory_and_ready_refunds_unused() {
        let probe = Arc::new(Probe::default());
        let mut prepared = PreparedWorker::new(context(&probe, false, false, true), factory);
        assert_eq!(probe.requests.load(Ordering::SeqCst), 0);
        assert!(
            prepared
                .admit(&memory(&probe, &factory, true, false))
                .is_err()
        );
        assert_eq!(probe.requests.load(Ordering::SeqCst), 1);
        assert_eq!(probe.factories.load(Ordering::SeqCst), 0);
        assert_eq!(probe.invocations.load(Ordering::SeqCst), 0);
        assert_eq!(probe.live.load(Ordering::SeqCst), 0);
        drop(prepared);
        assert!(probe.context_dropped.load(Ordering::SeqCst));

        let probe = Arc::new(Probe::default());
        let mut prepared = PreparedWorker::new(context(&probe, false, false, true), factory);
        prepared
            .admit(&memory(&probe, &factory, false, false))
            .unwrap();
        let original = prepared.into_context();
        assert_eq!(probe.live.load(Ordering::SeqCst), 0);
        assert_eq!(probe.factories.load(Ordering::SeqCst), 0);
        assert_eq!(probe.confirmations.load(Ordering::SeqCst), 0);
        assert!(!probe.context_dropped.load(Ordering::SeqCst));
        drop(original);
        assert!(probe.context_dropped.load(Ordering::SeqCst));
    }

    #[test]
    fn worker_function_same_owner_survives_queue_drop_or_one_shot_call_and_none() {
        for call in [false, true] {
            let probe = Arc::new(Probe::default());
            let mut prepared = PreparedWorker::new(context(&probe, false, false, true), factory);
            prepared
                .admit(&memory(&probe, &factory, false, false))
                .unwrap();
            let function = prepared.finish(42);
            assert_eq!(probe.requests.load(Ordering::SeqCst), 1);
            assert_eq!(probe.factories.load(Ordering::SeqCst), 1);
            assert_eq!(probe.confirmations.load(Ordering::SeqCst), 1);
            assert_eq!(probe.live.load(Ordering::SeqCst), 1);
            if call {
                invoke(function).unwrap();
            } else {
                drop(function);
            }
            assert_eq!(probe.invocations.load(Ordering::SeqCst), usize::from(call));
            assert!(probe.context_dropped.load(Ordering::SeqCst));
            assert!(probe.owner_dropped.load(Ordering::SeqCst));
            assert_eq!(probe.live.load(Ordering::SeqCst), 0);
        }
        let probe = Arc::new(Probe::default());
        let mut prepared = PreparedWorker::new(context(&probe, false, false, false), factory);
        prepared.admit(&None).unwrap();
        let function = prepared.finish(42);
        assert!(matches!(&function.0, Kind::Legacy(_)));
        invoke(function).unwrap();
        assert_eq!(probe.invocations.load(Ordering::SeqCst), 1);
        assert_eq!(probe.requests.load(Ordering::SeqCst), 0);
        assert!(probe.context_dropped.load(Ordering::SeqCst));
    }

    #[test]
    fn worker_function_confirmation_unwind_destroys_closure_before_refund() {
        let probe = Arc::new(Probe::default());
        let mut prepared = PreparedWorker::new(context(&probe, false, false, true), factory);
        prepared
            .admit(&memory(&probe, &factory, false, true))
            .unwrap();
        assert!(catch_unwind(AssertUnwindSafe(|| prepared.finish(42))).is_err());
        assert_eq!(probe.invocations.load(Ordering::SeqCst), 0);
        assert!(probe.context_dropped.load(Ordering::SeqCst));
        assert!(probe.owner_dropped.load(Ordering::SeqCst));
        assert_eq!(probe.live.load(Ordering::SeqCst), 0);
    }

    #[test]
    fn worker_function_call_or_destructor_unwind_retains_original_charge() {
        for call in [false, true] {
            let probe = Arc::new(Probe::default());
            let mut prepared = PreparedWorker::new(context(&probe, call, !call, true), factory);
            prepared
                .admit(&memory(&probe, &factory, false, false))
                .unwrap();
            let function = prepared.finish(42);
            assert!(
                catch_unwind(AssertUnwindSafe(|| {
                    if call {
                        let _ = invoke(function);
                    } else {
                        drop(function);
                    }
                }))
                .is_err()
            );
            assert!(probe.context_dropped.load(Ordering::SeqCst));
            assert!(!probe.owner_dropped.load(Ordering::SeqCst));
            assert_eq!(probe.live.load(Ordering::SeqCst), 1);
            assert_eq!(probe.requests.load(Ordering::SeqCst), 1);
        }
    }
}
