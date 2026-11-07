//! Implementation of calling Rust-defined functions from components.

#[cfg(feature = "component-model-async")]
use crate::component::concurrent::{self, Accessor, Status};
use crate::component::func::{LiftContext, LowerContext};
use crate::component::matching::InstanceType;
use crate::component::storage::{slice_to_storage, slice_to_storage_mut};
use crate::component::types::ComponentFunc;
use crate::component::{ComponentNamedList, Instance, Lift, Lower, Val};
use crate::prelude::*;
use crate::runtime::vm::component::{
    ComponentInstance, VMComponentContext, VMLowering, VMLoweringCallee,
};
use crate::runtime::vm::{VMOpaqueContext, VMStore};
use crate::store::Asyncness;
use crate::{AsContextMut, StoreContextMut, ValRaw};
use alloc::sync::Arc;
use core::any::Any;
use core::mem::{self, MaybeUninit};
#[cfg(feature = "async")]
use core::pin::Pin;
use core::ptr::NonNull;
use wasmtime_environ::component::{
    CanonicalAbiInfo, InterfaceType, MAX_FLAT_PARAMS, MAX_FLAT_RESULTS, OptionsIndex, TypeFuncIndex,
};

/// A host function suitable for passing into a component.
///
/// This structure represents a monomorphic host function that can only be used
/// in the specific context of a particular store. This is generally not too
/// too safe to use and is only meant for internal use.
pub struct HostFunc {
    /// The raw function pointer which Cranelift will invoke.
    entrypoint: VMLoweringCallee,

    /// The implementation of type-checking to ensure that this function
    /// ascribes to the provided function type.
    ///
    /// This is used, for example, when a component imports a host function and
    /// this will determine if the host function can be imported with the given
    /// type.
    typecheck: fn(TypeFuncIndex, &InstanceType<'_>) -> Result<()>,

    /// The actual host function.
    ///
    /// This is frequently an empty allocation in the sense that the underlying
    /// type is a zero-sized-type. Host functions are allowed, though, to close
    /// over the environment as well.
    func: Box<dyn Any + Send + Sync>,

    /// Whether or not this host function was defined in such a way that async
    /// stack switching is required when calling it.
    asyncness: Asyncness,
}

impl core::fmt::Debug for HostFunc {
    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        f.debug_struct("HostFunc").finish_non_exhaustive()
    }
}

/// An affine owner for a typed host reply's original native backing.
///
/// The builder must run only after `allocation` has admitted every backing
/// allocation it creates. The owner is confirmed after both fields exist, and
/// is released only after the actual reply has been destroyed. There is no
/// unowned extraction or cloning API.
///
/// This does not account arbitrary allocations made by a custom `Lower`
/// implementation, shared/interior owners, or data copied into an escaping
/// error. Embedders must audit their closed reply builders and lowering types;
/// it is not a generic transitive-memory guarantee for any `R: Lower`.
pub struct HostOutput<R> {
    value: R,
    allocation: Option<Box<dyn crate::NativeAllocation>>,
}

impl<R> HostOutput<R> {
    /// Build a reply while an already-admitted original backing owner is live.
    /// `None` is explicit legacy/unaccounted ownership, never an admission retry.
    pub fn build(
        allocation: Option<Box<dyn crate::NativeAllocation>>,
        build: impl FnOnce() -> R,
    ) -> Self {
        let mut output = Self {
            value: build(),
            allocation,
        };
        if let Some(owner) = &mut output.allocation {
            owner.allocated();
        }
        output
    }

    #[cfg(feature = "async")]
    fn lower_with(self, lower: impl FnOnce(&R) -> Result<()>) -> Result<()> {
        // Keep the actual R in this wrapper throughout lowering, including a
        // guest realloc suspension/error. The closed LSF reply Lower graph
        // only borrows its strings/lists; no original backing enters an Error.
        let result = lower(&self.value);
        drop(self);
        result
    }
}

enum HostResult<T> {
    Done(Result<T>),
    #[cfg(feature = "component-model-async")]
    Future(HostFuture<T>),
}

/// Own only the concrete engine callback-future Box, not its transitive values
/// or the separate async scheduler/accessor boxes. The native owner is outside
/// the allocation it protects, so the actual Box dies before its reservation.
#[cfg(feature = "component-model-async")]
struct HostFuture<T> {
    future: Pin<Box<dyn Future<Output = Result<T>> + Send>>,
    _allocation: Option<Box<dyn crate::NativeAllocation>>,
}

#[cfg(feature = "component-model-async")]
impl<T: 'static> HostResult<T> {
    fn future<F>(memory: crate::runtime::native_memory::Memory, future: F) -> Self
    where
        F: Future<Output = Result<T>> + Send + 'static,
    {
        match HostFuture::new(memory, future) {
            Ok(future) => Self::Future(future),
            Err(error) => Self::Done(Err(error)),
        }
    }
}

#[cfg(feature = "component-model-async")]
impl<T: 'static> HostFuture<T> {
    fn new<F>(memory: crate::runtime::native_memory::Memory, future: F) -> Result<Self>
    where
        F: Future<Output = Result<T>> + Send + 'static,
    {
        // The concrete type is still known before trait-object erasure. Pin
        // adds no allocation; a ZST Box has no backing allocation or owner.
        let allocation = crate::runtime::native_memory::reserve(
            &memory,
            core::alloc::Layout::new::<F>().size(),
        )?;
        let mut owner = Self {
            future: Box::pin(future),
            _allocation: allocation,
        };
        // Install both fields before confirmation: an unwinding callback
        // must destroy/deallocate the actual future before refunding it.
        if let Some(allocation) = owner._allocation.as_mut() {
            allocation.allocated();
        }
        Ok(owner)
    }
}

#[cfg(feature = "component-model-async")]
impl<T> Future for HostFuture<T> {
    type Output = Result<T>;

    fn poll(
        self: Pin<&mut Self>,
        cx: &mut core::task::Context<'_>,
    ) -> core::task::Poll<Self::Output> {
        self.get_mut().future.as_mut().poll(cx)
    }
}

impl HostFunc {
    /// Creates a new host function based on the implementation of `func`.
    ///
    /// The `asyncness` parameter indicates whether the `func` requires
    /// wasm to be on a fiber. This is used to propagate to the `Store` during
    /// instantiation to ensure that this guarantee is met.
    ///
    /// Note that if `asyncness` is mistaken then that'll result in panics
    /// in Wasmtime, but not memory unsafety.
    fn new<T, F, P, R>(asyncness: Asyncness, func: F) -> Result<Arc<HostFunc>>
    where
        T: 'static,
        R: Send + Sync + 'static,
        F: HostFn<T, P, R> + Send + Sync + 'static,
    {
        Ok(try_new::<Arc<_>>(HostFunc {
            entrypoint: F::cabi_entrypoint,
            typecheck: F::typecheck,
            func: try_new::<Box<_>>(func)?,
            asyncness,
        })?)
    }

    /// Equivalent for `Linker::func_wrap`
    pub(crate) fn func_wrap<T, F, P, R>(func: F) -> Result<Arc<HostFunc>>
    where
        T: 'static,
        F: Fn(StoreContextMut<T>, P) -> Result<R> + Send + Sync + 'static,
        P: ComponentNamedList + Lift + 'static,
        R: ComponentNamedList + Lower + 'static,
    {
        Self::new(
            Asyncness::No,
            StaticHostFn::<_, false>::new(move |store, params| {
                HostResult::Done(func(store, params))
            }),
        )
    }

    /// Stack-only, immediately-ready counterpart of `func_wrap_async`.
    #[cfg(feature = "async")]
    pub(crate) fn func_wrap_ready<T, F, P, R>(func: F) -> Result<Arc<HostFunc>>
    where
        T: Send + 'static,
        F: Fn(StoreContextMut<'_, T>, P) -> Result<R> + Send + Sync + 'static,
        P: ComponentNamedList + Lift + Send + 'static,
        R: ComponentNamedList + Lower + 'static,
    {
        Self::new(
            Asyncness::Yes,
            StaticHostFn::<_, false>::new(move |store, params| {
                HostResult::Done(store.with_blocking(|store, cx| {
                    let mut args = Some((store, params));
                    let future = core::future::poll_fn(|_| {
                        let (store, params) = args.take().expect("ready callback polled twice");
                        core::task::Poll::Ready(func(store, params))
                    });
                    cx.block_on(future).and_then(|result| result)
                }))
            }),
        )
    }

    /// Equivalent for `Linker::func_wrap_async`
    #[cfg(feature = "async")]
    pub(crate) fn func_wrap_async<T, F, P, R>(func: F) -> Result<Arc<HostFunc>>
    where
        T: 'static,
        F: Fn(StoreContextMut<'_, T>, P) -> Box<dyn Future<Output = Result<R>> + Send + '_>
            + Send
            + Sync
            + 'static,
        P: ComponentNamedList + Lift + 'static,
        R: ComponentNamedList + Lower + 'static,
    {
        Self::new(
            Asyncness::Yes,
            StaticHostFn::<_, false>::new(move |store, params| {
                HostResult::Done(
                    store
                        .block_on(|store| Pin::from(func(store, params)))
                        .and_then(|r| r),
                )
            }),
        )
    }

    /// Equivalent for `LinkerInstance::func_wrap_async_owned`.
    #[cfg(feature = "async")]
    pub(crate) fn func_wrap_async_owned<T, F, P, R>(func: F) -> Result<Arc<HostFunc>>
    where
        T: 'static,
        F: Fn(
                StoreContextMut<'_, T>,
                P,
            ) -> Box<dyn Future<Output = Result<HostOutput<R>>> + Send + '_>
            + Send
            + Sync
            + 'static,
        P: ComponentNamedList + Lift + 'static,
        R: ComponentNamedList + Lower + 'static,
    {
        Self::new(
            Asyncness::Yes,
            StaticOwnedHostFn::new(move |store, params| {
                HostResult::Done(
                    store
                        .block_on(|store| Pin::from(func(store, params)))
                        .and_then(|r| r),
                )
            }),
        )
    }

    /// Equivalent for `Linker::func_wrap_concurrent`
    #[cfg(feature = "component-model-async")]
    pub(crate) fn func_wrap_concurrent<T, F, P, R>(func: F) -> Result<Arc<HostFunc>>
    where
        T: 'static,
        F: Fn(&Accessor<T>, P) -> Pin<Box<dyn Future<Output = Result<R>> + Send + '_>>
            + Send
            + Sync
            + 'static,
        P: ComponentNamedList + Lift + 'static,
        R: ComponentNamedList + Lower + 'static,
    {
        let func = Arc::new(func);
        Self::new(
            Asyncness::Yes,
            StaticHostFn::<_, true>::new(move |store, params| {
                let func = func.clone();
                let memory = store.0.native_memory();
                HostResult::future(
                    memory,
                    store.wrap_call(move |accessor| func(accessor, params)),
                )
            }),
        )
    }

    /// Equivalent of `Linker::func_new`
    pub(crate) fn func_new<T, F>(func: F) -> Result<Arc<HostFunc>>
    where
        T: 'static,
        F: Fn(StoreContextMut<'_, T>, ComponentFunc, &[Val], &mut [Val]) -> Result<()>
            + Send
            + Sync
            + 'static,
    {
        Self::new(
            Asyncness::No,
            DynamicHostFn::<_, false>::new(
                move |store, ty, mut params_and_results, result_start| {
                    let (params, results) = params_and_results.split_at_mut(result_start);
                    let result = func(store, ty, params, results).map(move |()| params_and_results);
                    HostResult::Done(result)
                },
            ),
        )
    }

    /// Equivalent of `Linker::func_new_async`
    #[cfg(feature = "async")]
    pub(crate) fn func_new_async<T, F>(func: F) -> Result<Arc<HostFunc>>
    where
        T: 'static,
        F: for<'a> Fn(
                StoreContextMut<'a, T>,
                ComponentFunc,
                &'a [Val],
                &'a mut [Val],
            ) -> Box<dyn Future<Output = Result<()>> + Send + 'a>
            + Send
            + Sync
            + 'static,
    {
        Self::new(
            Asyncness::Yes,
            DynamicHostFn::<_, false>::new(
                move |store, ty, mut params_and_results, result_start| {
                    let (params, results) = params_and_results.split_at_mut(result_start);
                    let result = store
                        .with_blocking(|store, cx| {
                            cx.block_on(Pin::from(func(store, ty, params, results)))
                        })
                        .and_then(|r| r);
                    let result = result.map(move |()| params_and_results);
                    HostResult::Done(result)
                },
            ),
        )
    }

    /// Equivalent of `Linker::func_new_concurrent`
    #[cfg(feature = "component-model-async")]
    pub(crate) fn func_new_concurrent<T, F>(func: F) -> Result<Arc<HostFunc>>
    where
        T: 'static,
        F: for<'a> Fn(
                &'a Accessor<T>,
                ComponentFunc,
                &'a [Val],
                &'a mut [Val],
            ) -> Pin<Box<dyn Future<Output = Result<()>> + Send + 'a>>
            + Send
            + Sync
            + 'static,
    {
        let func = Arc::new(func);
        Self::new(
            Asyncness::Yes,
            DynamicHostFn::<_, true>::new(
                move |store, ty, mut params_and_results, result_start| {
                    let func = func.clone();
                    let memory = store.0.native_memory();
                    HostResult::future(
                        memory,
                        store.wrap_call(move |accessor| {
                            Box::pin(async move {
                                let (params, results) =
                                    params_and_results.split_at_mut(result_start);
                                func(accessor, ty, params, results).await?;
                                Ok(params_and_results)
                            })
                        }),
                    )
                },
            ),
        )
    }

    pub fn typecheck(&self, ty: TypeFuncIndex, types: &InstanceType<'_>) -> Result<()> {
        (self.typecheck)(ty, types)
    }

    pub fn lowering(&self) -> VMLowering {
        let data = NonNull::from(&*self.func).cast();
        VMLowering {
            callee: NonNull::new(self.entrypoint as *mut _).unwrap().into(),
            data: data.into(),
        }
    }

    pub fn asyncness(&self) -> Asyncness {
        self.asyncness
    }
}

/// Argument to [`HostFn::lift_params`]
enum Source<'a> {
    /// The parameters come from flat wasm arguments which are provided here.
    Flat(&'a [ValRaw]),
    /// The parameters come from linear memory at the provided offset, which is
    /// already validated to be in-bounds.
    Memory(usize),
}

/// Argument to [`HostFn::lower_result`]
enum Destination<'a> {
    /// The result is stored in flat parameters whose storage is provided here.
    Flat(&'a mut [MaybeUninit<ValRaw>]),
    /// The result is stored in linear memory at the provided offset, which is
    /// already validated to be in-bounds.
    Memory(usize),
}

/// Consolidation of functionality of invoking a host function.
///
/// This trait primarily serves as a deduplication of the "static" and
/// "dynamic" host function paths where all default functions here are shared
/// (source-wise at least) across the two styles of host functions.
trait HostFn<T, P, R>
where
    T: 'static,
    R: Send + Sync + 'static,
{
    /// Whether or not this is `async` function from the perspective of the
    /// component model.
    const ASYNC: bool;

    /// Performs a type-check to ensure that this host function can be imported
    /// with the provided signature that a component is using.
    fn typecheck(ty: TypeFuncIndex, types: &InstanceType<'_>) -> Result<()>;

    /// Execute this host function.
    fn run(&self, store: StoreContextMut<'_, T>, params: P) -> HostResult<R>;

    /// Performs the lifting operation to convert arguments from the canonical
    /// ABI in wasm memory/arguments into their Rust representation.
    fn lift_params(cx: &mut LiftContext<'_>, ty: TypeFuncIndex, source: Source<'_>) -> Result<P>;

    /// Performs the lowering operation to convert the result from its Rust
    /// representation to the canonical ABI representation.
    fn lower_result(
        cx: &mut LowerContext<'_, T>,
        ty: TypeFuncIndex,
        result: R,
        dst: Destination<'_>,
    ) -> Result<()>;

    /// Raw entrypoint invoked by Cranelift.
    ///
    /// # Safety
    ///
    /// This function is only safe when called from a trusted source which
    /// upholds at least these invariants:
    ///
    /// * `cx` is a valid pointer which comes from calling wasm.
    /// * `data` is a valid pointer to `Self`
    /// * `ty` and `options` are valid within the context of `cx`
    /// * `storage` and `storage_len` are valid pointers and correspond to
    ///   correctly initialized wasm arguments/results according to the
    ///   canonical ABI specified by `ty` and `options`.
    ///
    /// The code elsewhere in this trait is all downstream of this `unsafe`,
    /// and upholding this `unsafe` invariant requires Cranelift, function
    /// translation, the canonical ABI, and Wasmtime to all stay in sync.
    /// Basically we can't statically rule out this `unsafe`, we just gotta
    /// not have bugs.
    unsafe extern "C" fn cabi_entrypoint(
        cx: NonNull<VMOpaqueContext>,
        data: NonNull<u8>,
        ty: u32,
        options: u32,
        storage: NonNull<MaybeUninit<ValRaw>>,
        storage_len: usize,
    ) -> bool
    where
        Self: Sized,
    {
        let cx = unsafe { VMComponentContext::from_opaque(cx) };
        unsafe {
            ComponentInstance::enter_host_from_wasm(cx, |store, instance| {
                let mut store = store.unchecked_context_mut();
                let ty = TypeFuncIndex::from_u32(ty);
                let options = OptionsIndex::from_u32(options);
                let storage = NonNull::slice_from_raw_parts(storage, storage_len).as_mut();
                let data = data.cast::<Self>().as_ref();
                data.entrypoint(store.as_context_mut(), instance, ty, options, storage)
            })
        }
    }

    /// "Rust" entrypoint after panic-handling infrastructure is set up and raw
    /// arguments are translated to Rust types.
    fn entrypoint(
        &self,
        mut store: StoreContextMut<'_, T>,
        instance: Instance,
        ty: TypeFuncIndex,
        options: OptionsIndex,
        storage: &mut [MaybeUninit<ValRaw>],
    ) -> Result<()> {
        let vminstance = instance.id().get(store.0);
        let async_ = vminstance.component().env_component().options[options].async_;

        // If this is a synchronous-lower of a host-async function, then the
        // guest is blocking. Test, in the context of the guest task, if that's
        // allowed.
        if !async_ && Self::ASYNC {
            store.0.check_blocking()?;
        }

        if async_ {
            #[cfg(feature = "component-model-async")]
            {
                self.call_async_lower(store.as_context_mut(), instance, ty, options, storage)
            }
            #[cfg(not(feature = "component-model-async"))]
            unreachable!(
                "async-lowered imports should have failed validation \
                 when `component-model-async` feature disabled"
            );
        } else {
            self.call_sync_lower(store.as_context_mut(), instance, ty, options, storage)
        }
    }

    /// Implementation of the "sync" ABI.
    ///
    /// This is the implementation of invoking a host function through the
    /// synchronous ABI of the component model, or when a function doesn't have
    /// the `async` option when lowered. Note that the host function itself
    /// can still be async, in which case this will block here waiting for it
    /// to finish.
    fn call_sync_lower(
        &self,
        mut store: StoreContextMut<'_, T>,
        instance: Instance,
        ty: TypeFuncIndex,
        options: OptionsIndex,
        storage: &mut [MaybeUninit<ValRaw>],
    ) -> Result<()> {
        let entered_host_task = store.0.host_task_create()?;

        let mut lift = LiftContext::new(store.0.store_opaque_mut(), options, instance)?;
        let (params, rest) = self.load_params(&mut lift, ty, MAX_FLAT_PARAMS, storage)?;

        let ret = match self.run(store.as_context_mut(), params) {
            HostResult::Done(result) => result?,
            #[cfg(feature = "component-model-async")]
            HostResult::Future(future) => {
                concurrent::poll_and_block(store.0, entered_host_task, future)?
            }
        };

        let mut lower = LowerContext::new(store, options, instance);
        let fty = &lower.types[ty];
        let result_tys = &lower.types[fty.results];
        let dst = if let Some(cnt) = result_tys.abi.flat_count(MAX_FLAT_RESULTS) {
            Destination::Flat(&mut storage[..cnt])
        } else {
            // SAFETY: due to the contract of `entrypoint` we know that the
            // return pointer, located after the parameters, is initialized
            // by wasm and safe to read.
            let ptr = unsafe { rest[0].assume_init_ref() };
            Destination::Memory(validate_inbounds_dynamic(
                &result_tys.abi,
                lower.as_slice_mut(),
                ptr,
            )?)
        };
        lower.validate_scope_exit()?;
        lower.store.0.host_task_delete(entered_host_task)?;
        Self::lower_result(&mut lower, ty, ret, dst)
    }

    /// Implementation of the "async" ABI of the component model.
    ///
    /// This is invoked when a component has the `async` options specified on
    /// its `canon lower` for a host function. Note that the host function may
    /// be either sync or async, and that's handled here too.
    #[cfg(feature = "component-model-async")]
    fn call_async_lower(
        &self,
        store: StoreContextMut<'_, T>,
        instance: Instance,
        ty: TypeFuncIndex,
        options: OptionsIndex,
        storage: &mut [MaybeUninit<ValRaw>],
    ) -> Result<()> {
        use wasmtime_environ::component::MAX_FLAT_ASYNC_PARAMS;

        let (component, store) = instance.component_and_store_mut(store.0);
        let mut store = StoreContextMut(store);
        let types = component.types();
        let fty = &types[ty];
        let entered_host_task = store.0.host_task_create()?;

        // Lift the parameters, either from flat storage or from linear
        // memory.
        let mut lift = LiftContext::new(store.0.store_opaque_mut(), options, instance)?;
        let (params, rest) = self.load_params(&mut lift, ty, MAX_FLAT_ASYNC_PARAMS, storage)?;

        // Load/validate the return pointer, if present.
        let retptr = if !lift.types[fty.results].types.is_empty() {
            let mut lower = LowerContext::new(store.as_context_mut(), options, instance);
            // SAFETY: see `load_params` below about how the return pointer
            // should be safe to use.
            let ptr = unsafe { rest[0].assume_init_ref() };
            let result_tys = &lower.types[fty.results];
            validate_inbounds_dynamic(&result_tys.abi, lower.as_slice_mut(), ptr)?
        } else {
            // If there's no return pointer then `R` should have an
            // empty flat representation. In this situation pretend the return
            // pointer was 0 so we have something to shepherd along into the
            // closure below.
            0
        };

        let host_result = self.run(store.as_context_mut(), params);

        let rc = match host_result {
            HostResult::Done(result) => {
                let result = result?;
                let mut lower = LowerContext::new(store, options, instance);
                lower.validate_scope_exit()?;
                lower.store.0.host_task_delete(entered_host_task)?;
                Self::lower_result(&mut lower, ty, result, Destination::Memory(retptr))?;
                Status::Returned.pack(None)
            }
            HostResult::Future(future) => instance.first_poll(
                store.as_context_mut(),
                entered_host_task,
                future,
                move |store, ret, immediate| {
                    let mut lower = LowerContext::new(store, options, instance);
                    lower.validate_scope_exit()?;
                    if immediate {
                        lower.store.0.host_task_delete(entered_host_task)?;
                    }
                    // FIXME(WebAssembly/component-model#678) the currently
                    // running thread for this exit lower is wrong. This happens
                    // to pick whatever's in the store at the time of a
                    // non-immediate exit which is not correct. There's no real
                    // right answer here, hence the upstream issue.
                    if let Some(result) = ret {
                        Self::lower_result(&mut lower, ty, result, Destination::Memory(retptr))?;
                    }
                    Ok(())
                },
            )?,
        };

        storage[0].write(ValRaw::u32(rc));

        Ok(())
    }

    /// Loads parameters the wasm arguments `storage`.
    ///
    /// This will internally decide the ABI source of the parameters and use
    /// `storage` appropriately.
    fn load_params<'a>(
        &self,
        lift: &mut LiftContext<'_>,
        ty: TypeFuncIndex,
        max_flat_params: usize,
        storage: &'a [MaybeUninit<ValRaw>],
    ) -> Result<(P, &'a [MaybeUninit<ValRaw>])> {
        let fty = &lift.types[ty];
        let param_tys = &lift.types[fty.params];
        let param_flat_count = param_tys.abi.flat_count(max_flat_params);
        let src = match param_flat_count {
            Some(cnt) => {
                let params = &storage[..cnt];
                // SAFETY: due to the contract of `entrypoint` we are
                // guaranteed that all flat parameters are initialized by
                // compiled wasm.
                Source::Flat(unsafe { mem::transmute::<&[MaybeUninit<ValRaw>], &[ValRaw]>(params) })
            }
            None => {
                // SAFETY: due to the contract of `entrypoint` we are
                // guaranteed that the return pointer is initialized by
                // compiled wasm.
                let ptr = unsafe { storage[0].assume_init_ref() };
                Source::Memory(validate_inbounds_dynamic(
                    &param_tys.abi,
                    lift.memory(),
                    ptr,
                )?)
            }
        };
        let params = Self::lift_params(lift, ty, src)?;
        Ok((params, &storage[param_flat_count.unwrap_or(1)..]))
    }
}

/// Checks that a host function's `ASYNC`-ness (as encoded by which of
/// `func_new`/`func_new_async`/`func_new_concurrent` — or their `_wrap`
/// counterparts — constructed it) matches whether the component's WIT type
/// for this import is declared `async func`.
///
/// This isn't a case of one or the other being "correct": `func_new_async`/
/// `func_wrap_async` intentionally implement a *sync*-WIT-typed function via
/// blocking/async host code (see their docs), so they can never satisfy an
/// `async func` import — only `func_new_concurrent`/`func_wrap_concurrent`
/// can. The error message names which specific mismatch occurred and points
/// at the API that would work, since "type mismatch with async" alone gives
/// no indication of *why* or what to use instead.
fn typecheck_async(host_async: bool, wit_async: bool) -> Result<()> {
    if host_async == wit_async {
        return Ok(());
    }
    if wit_async {
        bail!(
            "type mismatch with async: this import is declared `async func` in WIT, but was \
             satisfied with a sync-style host function (`func_new`/`func_wrap`, or \
             `func_new_async`/`func_wrap_async` — despite the name, these implement a \
             *sync*-WIT-typed function via blocking host code, not an `async func` import); \
             use `func_new_concurrent`/`func_wrap_concurrent` instead"
        );
    } else {
        bail!(
            "type mismatch with async: this import's WIT type is a plain (non-`async`) \
             function, but was satisfied with `func_new_concurrent`/`func_wrap_concurrent`, \
             which is only for `async func`-typed imports; use `func_new`/`func_wrap` (or \
             `func_new_async`/`func_wrap_async` for blocking host code) instead"
        );
    }
}

/// Implementation of a "static" host function where the parameters and results
/// of a function are known at compile time.
#[repr(transparent)]
struct StaticHostFn<F, const ASYNC: bool>(F);

impl<F, const ASYNC: bool> StaticHostFn<F, ASYNC> {
    fn new<T, P, R>(func: F) -> Self
    where
        T: 'static,
        P: ComponentNamedList + Lift + 'static,
        R: ComponentNamedList + Lower + 'static,
        F: Fn(StoreContextMut<'_, T>, P) -> HostResult<R>,
    {
        Self(func)
    }
}

impl<T, F, P, R, const ASYNC: bool> HostFn<T, P, R> for StaticHostFn<F, ASYNC>
where
    T: 'static,
    F: Fn(StoreContextMut<'_, T>, P) -> HostResult<R>,
    P: ComponentNamedList + Lift + 'static,
    R: ComponentNamedList + Lower + 'static,
{
    const ASYNC: bool = ASYNC;

    fn typecheck(ty: TypeFuncIndex, types: &InstanceType<'_>) -> Result<()> {
        typed_typecheck::<P, R>(ASYNC, ty, types)
    }

    fn run(&self, store: StoreContextMut<'_, T>, params: P) -> HostResult<R> {
        (self.0)(store, params)
    }

    fn lift_params(cx: &mut LiftContext<'_>, ty: TypeFuncIndex, src: Source<'_>) -> Result<P> {
        typed_lift_params::<P>(cx, ty, src)
    }

    fn lower_result(
        cx: &mut LowerContext<'_, T>,
        ty: TypeFuncIndex,
        ret: R,
        dst: Destination<'_>,
    ) -> Result<()> {
        typed_lower_result(cx, ty, &ret, dst)
    }
}

#[cfg(feature = "async")]
struct StaticOwnedHostFn<F>(F);

#[cfg(feature = "async")]
impl<F> StaticOwnedHostFn<F> {
    fn new<T, P, R>(func: F) -> Self
    where
        T: 'static,
        P: ComponentNamedList + Lift + 'static,
        R: ComponentNamedList + Lower + 'static,
        F: Fn(StoreContextMut<'_, T>, P) -> HostResult<HostOutput<R>>,
    {
        Self(func)
    }
}

#[cfg(feature = "async")]
impl<T, F, P, R> HostFn<T, P, HostOutput<R>> for StaticOwnedHostFn<F>
where
    T: 'static,
    F: Fn(StoreContextMut<'_, T>, P) -> HostResult<HostOutput<R>>,
    P: ComponentNamedList + Lift + 'static,
    R: ComponentNamedList + Lower + 'static,
{
    const ASYNC: bool = false;

    fn typecheck(ty: TypeFuncIndex, types: &InstanceType<'_>) -> Result<()> {
        typed_typecheck::<P, R>(false, ty, types)
    }

    fn run(&self, store: StoreContextMut<'_, T>, params: P) -> HostResult<HostOutput<R>> {
        (self.0)(store, params)
    }

    fn lift_params(cx: &mut LiftContext<'_>, ty: TypeFuncIndex, src: Source<'_>) -> Result<P> {
        typed_lift_params::<P>(cx, ty, src)
    }

    fn lower_result(
        cx: &mut LowerContext<'_, T>,
        ty: TypeFuncIndex,
        ret: HostOutput<R>,
        dst: Destination<'_>,
    ) -> Result<()> {
        ret.lower_with(|value| typed_lower_result(cx, ty, value, dst))
    }
}

fn typed_typecheck<P: ComponentNamedList, R: ComponentNamedList>(
    async_: bool,
    ty: TypeFuncIndex,
    types: &InstanceType<'_>,
) -> Result<()> {
    let ty = &types.types[ty];
    typecheck_async(async_, ty.async_)?;
    P::typecheck(&InterfaceType::Tuple(ty.params), types)
        .context("type mismatch with parameters")?;
    R::typecheck(&InterfaceType::Tuple(ty.results), types).context("type mismatch with results")?;
    Ok(())
}

fn typed_lift_params<P: ComponentNamedList + Lift>(
    cx: &mut LiftContext<'_>,
    ty: TypeFuncIndex,
    src: Source<'_>,
) -> Result<P> {
    let ty = InterfaceType::Tuple(cx.types[ty].params);
    match src {
        Source::Flat(storage) => {
            // SAFETY: the contract of `ComponentType` for `P` means that
            // it's safe to interpret the parameters `storage` as
            // `P::Lower`. The contract of `entrypoint` is that everything
            // is initialized correctly internally.
            let storage: &P::Lower = unsafe { slice_to_storage(storage) };
            P::linear_lift_from_flat(cx, ty, storage)
        }
        Source::Memory(offset) => {
            P::linear_lift_from_memory(cx, ty, &cx.memory()[offset..][..P::SIZE32])
        }
    }
}

fn typed_lower_result<T, R: ComponentNamedList + Lower>(
    cx: &mut LowerContext<'_, T>,
    ty: TypeFuncIndex,
    ret: &R,
    dst: Destination<'_>,
) -> Result<()> {
    let fty = &cx.types[ty];
    let ty = InterfaceType::Tuple(fty.results);
    match dst {
        Destination::Flat(storage) => {
            // SAFETY: the contract of `ComponentType` for `R` means that
            // it's safe to reinterpret `ValRaw` storage to initialize as
            // `R::Lower`.
            let storage: &mut MaybeUninit<R::Lower> = unsafe { slice_to_storage_mut(storage) };
            ret.linear_lower_to_flat(cx, ty, storage)
        }
        Destination::Memory(ptr) => ret.linear_lower_to_memory(cx, ty, ptr),
    }
}

/// Implementation of a "dynamic" host function where the number of parameters,
/// types of parameters, and result type/presence, are all not known at compile
/// time.
///
/// This is intended for more-dynamic use cases than `StaticHostFn` above such
/// as demos, gluing things together quickly, and `wast` testing.
struct DynamicHostFn<F, const ASYNC: bool>(F);

impl<F, const ASYNC: bool> DynamicHostFn<F, ASYNC> {
    fn new<T>(func: F) -> Self
    where
        T: 'static,
        F: Fn(StoreContextMut<'_, T>, ComponentFunc, Vec<Val>, usize) -> HostResult<Vec<Val>>,
    {
        Self(func)
    }
}

impl<T, F, const ASYNC: bool> HostFn<T, (ComponentFunc, Vec<Val>), Vec<Val>>
    for DynamicHostFn<F, ASYNC>
where
    T: 'static,
    F: Fn(StoreContextMut<'_, T>, ComponentFunc, Vec<Val>, usize) -> HostResult<Vec<Val>>,
{
    const ASYNC: bool = ASYNC;

    /// This function performs dynamic type checks on its parameters and
    /// results and subsequently does not need to perform up-front type
    /// checks. However, we _do_ verify async-ness here.
    fn typecheck(ty: TypeFuncIndex, types: &InstanceType<'_>) -> Result<()> {
        let ty = &types.types[ty];
        typecheck_async(ASYNC, ty.async_)
    }

    fn run(
        &self,
        store: StoreContextMut<'_, T>,
        (ty, mut params): (ComponentFunc, Vec<Val>),
    ) -> HostResult<Vec<Val>> {
        let offset = params.len();
        for _ in 0..ty.results().len() {
            params.push(Val::Bool(false));
        }
        (self.0)(store, ty, params, offset)
    }

    fn lift_params(
        cx: &mut LiftContext<'_>,
        ty: TypeFuncIndex,
        src: Source<'_>,
    ) -> Result<(ComponentFunc, Vec<Val>)> {
        let param_tys = &cx.types[cx.types[ty].params];
        let mut params = Vec::new();
        match src {
            Source::Flat(storage) => {
                let mut iter = storage.iter();
                for ty in param_tys.types.iter() {
                    params.push(Val::lift(cx, *ty, &mut iter)?);
                }
                assert!(iter.next().is_none());
            }
            Source::Memory(mut offset) => {
                for ty in param_tys.types.iter() {
                    let abi = cx.types.canonical_abi(ty);
                    let size = usize::try_from(abi.size32).unwrap();
                    let memory = &cx.memory()[abi.next_field32_size(&mut offset)..][..size];
                    params.push(Val::load(cx, *ty, memory)?);
                }
            }
        }

        Ok((ComponentFunc::from(ty, &cx.instance_type()), params))
    }

    fn lower_result(
        cx: &mut LowerContext<'_, T>,
        ty: TypeFuncIndex,
        result_vals: Vec<Val>,
        dst: Destination<'_>,
    ) -> Result<()> {
        let fty = &cx.types[ty];
        let param_tys = &cx.types[fty.params];
        let result_tys = &cx.types[fty.results];
        let result_vals = &result_vals[param_tys.types.len()..];
        match dst {
            Destination::Flat(storage) => {
                let mut dst = storage.iter_mut();
                for (val, ty) in result_vals.iter().zip(result_tys.types.iter()) {
                    val.lower(cx, *ty, &mut dst)?;
                }
                assert!(dst.next().is_none());
            }
            Destination::Memory(mut ptr) => {
                for (val, ty) in result_vals.iter().zip(result_tys.types.iter()) {
                    let offset = cx.types.canonical_abi(ty).next_field32_size(&mut ptr);
                    val.store(cx, *ty, offset)?;
                }
            }
        }
        Ok(())
    }
}

pub(crate) fn validate_inbounds_dynamic(
    abi: &CanonicalAbiInfo,
    memory: &[u8],
    ptr: &ValRaw,
) -> Result<usize> {
    // FIXME(#4311): needs memory64 support
    let ptr = usize::try_from(ptr.get_u32())?;
    if ptr % usize::try_from(abi.align32)? != 0 {
        bail!("pointer not aligned");
    }
    let end = match ptr.checked_add(usize::try_from(abi.size32).unwrap()) {
        Some(n) => n,
        None => bail!("pointer size overflow"),
    };
    if end > memory.len() {
        bail!("pointer out of bounds")
    }
    Ok(ptr)
}

#[cfg(all(
    test,
    feature = "std",
    feature = "component-model-async",
    feature = "cranelift",
    feature = "wat"
))]
mod ready_only_tests {
    use super::*;
    use crate::component::{Component, ComponentType, Linker, TypedFunc};
    use crate::{Config, Engine, Store};
    use core::mem::MaybeUninit;
    use futures::FutureExt;
    use std::panic::AssertUnwindSafe;
    use std::sync::{Arc, Mutex};

    const COMPONENT: &str = r#"(component
      (type $host-type (func (param "arg" u32) (result u32)))
      (import "handle" (func $handle (type $host-type)))
      (core func $handle-core (canon lower (func $handle)))
      (core module $guest
        (import "host" "handle" (func $handle (param i32) (result i32)))
        (func (export "run") (param i32) (result i32) local.get 0 call $handle)
        (func (export "noop") (result i32) i32.const 7))
      (core instance $host (export "handle" (func $handle-core)))
      (core instance $guest (instantiate $guest (with "host" (instance $host))))
      (alias core export $guest "run" (core func $run))
      (alias core export $guest "noop" (core func $noop))
      (func (export "run") (param "arg" u32) (result u32) (canon lift (core func $run)))
      (func (export "noop") (result u32) (canon lift (core func $noop)))
    )"#;

    type Events = Arc<Mutex<Vec<&'static str>>>;
    struct Data {
        events: Events,
        nested: Option<TypedFunc<(), (u32,)>>,
    }
    struct Scope(Events);
    impl Drop for Scope {
        fn drop(&mut self) {
            self.0.lock().unwrap().push("body-drop");
        }
    }
    struct Guarded {
        value: u32,
        events: Events,
    }
    impl Drop for Guarded {
        fn drop(&mut self) {
            self.events.lock().unwrap().push("reply-drop");
        }
    }
    // SAFETY: this closed test type forwards exactly u32's canonical ABI,
    // typecheck and lowering; the test-only event owner is never encoded.
    unsafe impl ComponentType for Guarded {
        type Lower = <u32 as ComponentType>::Lower;
        const ABI: CanonicalAbiInfo = <u32 as ComponentType>::ABI;
        const IS_RUST_UNIT_TYPE: bool = <u32 as ComponentType>::IS_RUST_UNIT_TYPE;
        const MAY_REQUIRE_REALLOC: bool = <u32 as ComponentType>::MAY_REQUIRE_REALLOC;
        fn typecheck(ty: &InterfaceType, types: &InstanceType<'_>) -> Result<()> {
            <u32 as ComponentType>::typecheck(ty, types)
        }
    }
    // SAFETY: each implementation delegates to the existing u32 lowering
    // without touching the destination or changing its canonical layout.
    unsafe impl Lower for Guarded {
        fn linear_lower_to_flat<T>(
            &self,
            cx: &mut LowerContext<'_, T>,
            ty: InterfaceType,
            dst: &mut MaybeUninit<Self::Lower>,
        ) -> Result<()> {
            self.events.lock().unwrap().push("lower-live");
            self.value.linear_lower_to_flat(cx, ty, dst)
        }
        fn linear_lower_to_memory<T>(
            &self,
            cx: &mut LowerContext<'_, T>,
            ty: InterfaceType,
            offset: usize,
        ) -> Result<()> {
            self.events.lock().unwrap().push("lower-live");
            self.value.linear_lower_to_memory(cx, ty, offset)
        }
    }
    fn prepare(mut store: StoreContextMut<'_, Data>, arg: u32) -> Result<Events> {
        let events = store.data().events.clone();
        events.lock().unwrap().push("body-enter");
        let _scope = Scope(events.clone());
        // This is the exact field tested by Wasmtime's blocking gate. It is
        // absent for the duration of the existing boxed callback's poll.
        assert!(!store.0.can_block());
        events.lock().unwrap().push("blocking-context-held");
        let nested = store.data().nested.unwrap();
        let error = nested.call(&mut store, ()).unwrap_err();
        assert!(error.to_string().contains("requires that `*_async`"));
        events.lock().unwrap().push("reentry-denied");
        match arg {
            1 => return Err(crate::Error::msg("ready-test-refused")),
            2 => panic!("ready-test-panic"),
            _ => {}
        }
        Ok(events)
    }
    fn execute(store: StoreContextMut<'_, Data>, arg: u32) -> Result<(Guarded,)> {
        Ok((Guarded {
            value: 42,
            events: prepare(store, arg)?,
        },))
    }
    async fn exercise(ready: bool, concurrent: bool, arg: u32) -> (String, Vec<&'static str>) {
        let mut config = Config::new();
        config
            .wasm_component_model(true)
            .wasm_component_model_async(concurrent)
            .concurrency_support(concurrent);
        let engine = Engine::new(&config).unwrap();
        let component = Component::new(&engine, COMPONENT).unwrap();
        let mut linker = Linker::<Data>::new(&engine);
        if ready {
            linker
                .root()
                .func_wrap_ready("handle", |store, (arg,): (u32,)| execute(store, arg))
                .unwrap();
        } else {
            linker
                .root()
                .func_wrap_async("handle", |store, (arg,): (u32,)| {
                    Box::new(async move { execute(store, arg) })
                })
                .unwrap();
        }
        let events = Arc::new(Mutex::new(Vec::new()));
        let mut store = Store::new(
            &engine,
            Data {
                events: events.clone(),
                nested: None,
            },
        );
        let instance = linker
            .instantiate_async(&mut store, &component)
            .await
            .unwrap();
        let nested = instance
            .get_typed_func::<(), (u32,)>(&mut store, "noop")
            .unwrap();
        store.data_mut().nested = Some(nested);
        let run = instance
            .get_typed_func::<(u32,), (u32,)>(&mut store, "run")
            .unwrap();
        let outcome = AssertUnwindSafe(run.call_async(&mut store, (arg,)))
            .catch_unwind()
            .await;
        let status = match outcome {
            Ok(Ok((value,))) => format!("ok:{value}"),
            Ok(Err(error)) => {
                assert!(
                    error
                        .chain()
                        .any(|cause| cause.to_string().contains("ready-test-refused"))
                );
                "refused".to_owned()
            }
            Err(_) => "panic".to_owned(),
        };
        // Either completion or unwind must have restored the context and left
        // this Store outside any running fiber.
        assert!(!store.as_context_mut().0.can_block());
        let events = events.lock().unwrap().clone();
        (status, events)
    }
    #[tokio::test]
    async fn ready_callbacks_match_boxed_fiber_refusal_unwind_reentry_and_lowering() {
        for concurrent in [false, true] {
            for arg in [0, 1, 2] {
                let boxed = exercise(false, concurrent, arg).await;
                let ready = exercise(true, concurrent, arg).await;
                assert_eq!(ready, boxed, "concurrent={concurrent}, arg={arg}");
                let expected = match arg {
                    0 => (
                        "ok:42",
                        vec![
                            "body-enter",
                            "blocking-context-held",
                            "reentry-denied",
                            "body-drop",
                            "lower-live",
                            "reply-drop",
                        ],
                    ),
                    1 => (
                        "refused",
                        vec![
                            "body-enter",
                            "blocking-context-held",
                            "reentry-denied",
                            "body-drop",
                        ],
                    ),
                    2 => (
                        "panic",
                        vec![
                            "body-enter",
                            "blocking-context-held",
                            "reentry-denied",
                            "body-drop",
                        ],
                    ),
                    _ => unreachable!(),
                };
                assert_eq!(ready.0, expected.0);
                assert_eq!(ready.1, expected.1);
            }
        }
    }
    const MEMORY_COMPONENT: &str = r#"(component
  (type $host-type (func (param "arg" u32) (result (tuple u32 u32))))
  (import "handle" (func $handle (type $host-type)))
  (core module $mem (memory (export "memory") 1))
  (core instance $mem-inst (instantiate $mem))
  (alias core export $mem-inst "memory" (core memory $memory))
  (core func $handle-core (canon lower (func $handle) (memory $memory)))
  (core module $guest
    (import "host" "memory" (memory 1))
    (import "host" "handle" (func $handle (param i32 i32)))
    (func (export "run") (param i32) (result i32)
      local.get 0 i32.const 0 call $handle i32.const 0)
    (func (export "noop") (result i32) i32.const 7)
    (func (export "bad") (param i32) (result i32) local.get 0 i32.const 65535 call $handle i32.const 0))
  (core instance $host
    (export "memory" (memory $memory))
    (export "handle" (func $handle-core)))
  (core instance $guest (instantiate $guest (with "host" (instance $host))))
  (alias core export $guest "run" (core func $run))
  (alias core export $guest "noop" (core func $noop))
  (alias core export $guest "bad" (core func $bad))
  (func (export "run") (param "arg" u32) (result (tuple u32 u32)) (canon lift (core func $run) (memory $memory)))
  (func (export "noop") (result u32) (canon lift (core func $noop)))
  (func (export "bad") (param "arg" u32) (result (tuple u32 u32)) (canon lift (core func $bad) (memory $memory)))
)"#;

    struct GuardedPair {
        value: (u32, u32),
        events: Events,
    }
    impl Drop for GuardedPair {
        fn drop(&mut self) {
            self.events.lock().unwrap().push("reply-drop");
        }
    }
    // SAFETY: this test wrapper uses the existing pair's canonical ABI and
    // delegates type checking and both lowering paths without modifying data.
    unsafe impl ComponentType for GuardedPair {
        type Lower = <(u32, u32) as ComponentType>::Lower;
        const ABI: CanonicalAbiInfo = <(u32, u32) as ComponentType>::ABI;
        const IS_RUST_UNIT_TYPE: bool = <(u32, u32) as ComponentType>::IS_RUST_UNIT_TYPE;
        const MAY_REQUIRE_REALLOC: bool = <(u32, u32) as ComponentType>::MAY_REQUIRE_REALLOC;
        fn typecheck(ty: &InterfaceType, types: &InstanceType<'_>) -> Result<()> {
            <(u32, u32) as ComponentType>::typecheck(ty, types)
        }
    }
    // SAFETY: the value and destination are forwarded to the tuple's Lower.
    unsafe impl Lower for GuardedPair {
        fn linear_lower_to_flat<T>(
            &self,
            cx: &mut LowerContext<'_, T>,
            ty: InterfaceType,
            dst: &mut MaybeUninit<Self::Lower>,
        ) -> Result<()> {
            self.events.lock().unwrap().push("lower-flat-live");
            self.value.linear_lower_to_flat(cx, ty, dst)
        }
        fn linear_lower_to_memory<T>(
            &self,
            cx: &mut LowerContext<'_, T>,
            ty: InterfaceType,
            offset: usize,
        ) -> Result<()> {
            self.events.lock().unwrap().push("lower-memory-live");
            self.value.linear_lower_to_memory(cx, ty, offset)
        }
    }
    fn execute_pair(store: StoreContextMut<'_, Data>, arg: u32) -> Result<(GuardedPair,)> {
        Ok((GuardedPair {
            value: (42, 43),
            events: prepare(store, arg)?,
        },))
    }
    async fn memory_exercise(
        ready: bool,
        concurrent: bool,
        bad: bool,
    ) -> (String, Vec<&'static str>) {
        let mut config = Config::new();
        config
            .wasm_component_model(true)
            .wasm_component_model_async(concurrent)
            .concurrency_support(concurrent);
        let engine = Engine::new(&config).unwrap();
        let component = Component::new(&engine, MEMORY_COMPONENT).unwrap();
        let mut linker = Linker::<Data>::new(&engine);
        if ready {
            linker
                .root()
                .func_wrap_ready("handle", |store, (arg,): (u32,)| execute_pair(store, arg))
                .unwrap();
        } else {
            linker
                .root()
                .func_wrap_async("handle", |store, (arg,): (u32,)| {
                    Box::new(async move { execute_pair(store, arg) })
                })
                .unwrap();
        }
        let events = Arc::new(Mutex::new(Vec::new()));
        let mut store = Store::new(
            &engine,
            Data {
                events: events.clone(),
                nested: None,
            },
        );
        let instance = linker
            .instantiate_async(&mut store, &component)
            .await
            .unwrap();
        store.data_mut().nested = Some(
            instance
                .get_typed_func::<(), (u32,)>(&mut store, "noop")
                .unwrap(),
        );
        let func = instance
            .get_typed_func::<(u32,), ((u32, u32),)>(&mut store, if bad { "bad" } else { "run" })
            .unwrap();
        let result = func.call_async(&mut store, (0,)).await;
        let status = match result {
            Ok(((first, second),)) => format!("ok:{first},{second}"),
            Err(_) => "destination-refused".to_owned(),
        };
        assert!(!store.as_context_mut().0.can_block());
        let events = events.lock().unwrap().clone();
        (status, events)
    }
    #[tokio::test]
    async fn ready_callbacks_retain_reply_through_memory_lowering_and_destination_refusal() {
        for concurrent in [false, true] {
            for bad in [false, true] {
                let boxed = memory_exercise(false, concurrent, bad).await;
                let ready = memory_exercise(true, concurrent, bad).await;
                assert_eq!(ready, boxed, "concurrent={concurrent}, bad={bad}");
                if bad {
                    assert_eq!(ready.0, "destination-refused");
                    assert_eq!(
                        ready.1,
                        [
                            "body-enter",
                            "blocking-context-held",
                            "reentry-denied",
                            "body-drop",
                            "reply-drop"
                        ]
                    );
                } else {
                    assert_eq!(ready.0, "ok:42,43");
                    assert_eq!(
                        ready.1,
                        [
                            "body-enter",
                            "blocking-context-held",
                            "reentry-denied",
                            "body-drop",
                            "lower-memory-live",
                            "reply-drop"
                        ]
                    );
                }
            }
        }
    }
}
