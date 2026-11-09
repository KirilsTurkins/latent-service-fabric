//! Diagnostic: real canonical resource dispatch with a synthetic upload.
//!
//! This direct Linker control deliberately bypasses component authentication.
//! It does not create a real prepaid preparation, run the HTTP provider,
//! exercise its pending write, or qualify a C guest.
use super::{table, upload_window, wit, Error, HostState, Kind, Value};
use crate::host::native_context_reply_tests::{engine, ledger, store};
use latent_capabilities::broker::{
    io::IoFuture,
    streaming_http::{HttpBody, HttpUpload, PreparedHttpUpload, UPLOAD_WINDOW_INTERFACE},
};
use latent_core::BudgetProfile;
use std::{
    future::{pending, poll_fn, Future},
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, Mutex,
    },
    task::Poll,
};
use wasm_encoder::*;
use wasmtime::{
    component::{Accessor, Component as RuntimeComponent, InlineConcurrentHost, Linker, Resource},
    StoreContextMut,
};

type Events = Arc<Mutex<Vec<&'static str>>>;

struct WaitScope(Events, &'static str);
impl Drop for WaitScope {
    fn drop(&mut self) {
        self.0.lock().unwrap().push(self.1);
    }
}

struct Upload(Events);
impl Drop for Upload {
    fn drop(&mut self) {
        self.0.lock().unwrap().push("upload-drop");
    }
}
impl HttpUpload for Upload {
    fn write(&mut self, _: Vec<u8>) -> IoFuture<'_, Result<(), Error>> {
        IoFuture::failed(Error::InvalidState)
    }
    fn finish(self: Box<Self>) -> IoFuture<'static, Result<Box<dyn HttpBody>, Error>> {
        IoFuture::failed(Error::InvalidState)
    }
}

struct Wait(Arc<AtomicBool>, Events);
impl InlineConcurrentHost<HostState, (), ()> for Wait {
    fn invoke<'a>(
        &'a self,
        _: &'a Accessor<HostState>,
        (): (),
    ) -> impl Future<Output = wasmtime::Result<()>> + Send + 'a {
        async move {
            let _scope = WaitScope(self.1.clone(), "wait-dropped");
            self.1.lock().unwrap().push("wait-entered");
            self.0.store(true, Ordering::SeqCst);
            pending::<()>().await;
            Ok(())
        }
    }
}

struct BorrowWait {
    rep: u32,
    events: Events,
}
impl InlineConcurrentHost<HostState, (Resource<wit::Upload>,), ()> for BorrowWait {
    fn invoke<'a>(
        &'a self,
        _: &'a Accessor<HostState>,
        (target,): (Resource<wit::Upload>,),
    ) -> impl Future<Output = wasmtime::Result<()>> + Send + 'a {
        async move {
            assert_eq!(
                target.rep(),
                self.rep,
                "the same original upload is borrowed"
            );
            let _scope = WaitScope(self.events.clone(), "borrow-dropped");
            self.events.lock().unwrap().push("borrow-entered");
            pending::<()>().await;
            Ok(())
        }
    }
}

// Only the exact imported resource type is required by these three modes.
// 0: canonical drop then marker; 1: trap with own resource; 2: wait with it;
// 3: drop the same owned handle while a real canonical borrow is still pending.
fn component_bytes(interface: &str) -> Vec<u8> {
    let mut component = Component::new();
    let mut instance = InstanceType::new();
    instance.export("upload", ComponentTypeRef::Type(TypeBounds::SubResource));
    let mut types = ComponentTypeSection::new();
    types.instance(&instance); // type 0
    component.section(&types);
    let mut imports = ComponentImportSection::new();
    imports.import(interface, ComponentTypeRef::Instance(0)); // instance 0
    component.section(&imports);
    let mut aliases = ComponentAliasSection::new();
    aliases.alias(Alias::InstanceExport {
        instance: 0,
        kind: ComponentExportKind::Type,
        name: "upload",
    }); // type 1
    component.section(&aliases);
    let mut types = ComponentTypeSection::new();
    types.defined_type().own(1); // type 2
    types
        .function()
        .params([
            ("upload", ComponentValType::Type(2)),
            ("mode", PrimitiveValType::U32.into()),
        ])
        .result(None); // type 3
    types
        .function()
        .params([] as [(&str, ComponentValType); 0])
        .result(None); // type 4
    types
        .function()
        .async_(true)
        .params([] as [(&str, ComponentValType); 0])
        .result(None); // type 5
    types.defined_type().borrow(1); // type 6
    types
        .function()
        .async_(true)
        .params([("upload", ComponentValType::Type(6))])
        .result(None); // type 7
    component.section(&types);
    let mut imports = ComponentImportSection::new();
    imports.import("marker", ComponentTypeRef::Func(4)); // function 0
    imports.import("wait", ComponentTypeRef::Func(5)); // function 1
    imports.import("hold", ComponentTypeRef::Func(7)); // function 2
    component.section(&imports);
    let mut canon = CanonicalFunctionSection::new();
    canon.lower(0, []); // core function 0
    canon.lower(1, []); // core function 1; synchronous guest waits for host
    canon.lower(2, [CanonicalOption::Async]); // core function 2; one live borrow
    canon.resource_drop(1); // core function 3
    component.section(&canon);
    component.section(&ModuleSection(&caller()));
    let mut instances = InstanceSection::new();
    instances.export_items([
        ("marker", ExportKind::Func, 0),
        ("wait", ExportKind::Func, 1),
        ("hold", ExportKind::Func, 2),
        ("drop-upload", ExportKind::Func, 3),
    ]);
    instances.instantiate(0, [("host", ModuleArg::Instance(0))]);
    component.section(&instances);
    let mut aliases = ComponentAliasSection::new();
    aliases.alias(Alias::CoreInstanceExport {
        instance: 1,
        kind: ExportKind::Func,
        name: "run",
    }); // core function 4
    component.section(&aliases);
    let mut canon = CanonicalFunctionSection::new();
    canon.lift(4, 3, []); // component function 3
    component.section(&canon);
    let mut exports = ComponentExportSection::new();
    exports.export("run", ComponentExportKind::Func, 3, None);
    component.section(&exports);
    let bytes = component.finish();
    wasmparser::Validator::new_with_features(wasmparser::WasmFeatures::all())
        .validate_all(&bytes)
        .expect("diagnostic component must validate");
    bytes
}

fn caller() -> Module {
    let mut module = Module::new();
    let mut types = TypeSection::new();
    types.ty().function([], []); // marker and wait
    types.ty().function([ValType::I32], [ValType::I32]); // async borrow
    types.ty().function([ValType::I32], []); // canonical drop
    types.ty().function([ValType::I32, ValType::I32], []); // run
    module.section(&types);
    let mut imports = ImportSection::new();
    imports.import("host", "marker", EntityType::Function(0));
    imports.import("host", "wait", EntityType::Function(0));
    imports.import("host", "hold", EntityType::Function(1));
    imports.import("host", "drop-upload", EntityType::Function(2));
    module.section(&imports);
    let mut functions = FunctionSection::new();
    functions.function(3);
    module.section(&functions);
    let mut exports = ExportSection::new();
    exports.export("run", ExportKind::Func, 4);
    module.section(&exports);
    let mut body = Function::new([(1, ValType::I32)]);
    for instruction in [
        Instruction::LocalGet(1),
        Instruction::I32Eqz,
        Instruction::If(BlockType::Empty),
        Instruction::LocalGet(0),
        Instruction::Call(3),
        Instruction::Call(0),
        Instruction::Return,
        Instruction::End,
        Instruction::LocalGet(1),
        Instruction::I32Const(1),
        Instruction::I32Eq,
        Instruction::If(BlockType::Empty),
        Instruction::Call(0),
        Instruction::Unreachable,
        Instruction::End,
        Instruction::LocalGet(1),
        Instruction::I32Const(2),
        Instruction::I32Eq,
        Instruction::If(BlockType::Empty),
        Instruction::Call(1),
        Instruction::End,
        Instruction::LocalGet(1),
        Instruction::I32Const(3),
        Instruction::I32Eq,
        Instruction::If(BlockType::Empty),
        Instruction::LocalGet(0),
        Instruction::Call(2),
        Instruction::LocalTee(2),
        Instruction::I32Const(15),
        Instruction::I32And,
        Instruction::I32Const(1),
        Instruction::I32Ne,
        Instruction::If(BlockType::Empty),
        Instruction::Unreachable,
        Instruction::End,
        Instruction::Call(0),
        Instruction::LocalGet(0),
        Instruction::Call(3),
        Instruction::Unreachable,
        Instruction::End,
        Instruction::Unreachable,
        Instruction::End,
    ] {
        body.instruction(&instruction);
    }
    let mut code = CodeSection::new();
    code.function(&body);
    module.section(&code);
    module
}

async fn diagnostic(mode: u32, interface: &str) -> Vec<&'static str> {
    let engine = engine();
    let budget = ledger(BudgetProfile::Phase3);
    let mut store = store(&engine, &budget, true);
    store.fuel_async_yield_interval(None).unwrap();
    store.data_mut().capabilities.streams = table::diagnostic_table();
    let events: Events = Arc::new(Mutex::new(Vec::new()));
    let rep = store
        .data_mut()
        .capabilities
        .streams
        .reserve(Kind::Upload)
        .unwrap();
    store
        .data_mut()
        .capabilities
        .streams
        .put(
            rep,
            Kind::Upload,
            Value::WindowedUpload(PreparedHttpUpload {
                prepared: None,
                upload: Box::new(Upload(events.clone())),
                generation: 1,
            }),
        )
        .unwrap();

    let mut linker = Linker::new(&engine);
    if interface == UPLOAD_WINDOW_INTERFACE {
        upload_window::install(&mut linker).unwrap();
    } else {
        let mut instance = linker.instance(interface).unwrap();
        super::resources(&mut instance).unwrap();
    }
    let marker_events = events.clone();
    linker
        .root()
        .func_wrap(
            "marker",
            move |_: StoreContextMut<'_, HostState>, (): ()| {
                marker_events.lock().unwrap().push("guest-marker");
                Ok(())
            },
        )
        .unwrap();
    let entered = Arc::new(AtomicBool::new(false));
    linker
        .root()
        .func_wrap_concurrent_inline("wait", Wait(entered.clone(), events.clone()))
        .unwrap();
    linker
        .root()
        .func_wrap_concurrent_inline(
            "hold",
            BorrowWait {
                rep,
                events: events.clone(),
            },
        )
        .unwrap();
    let component = RuntimeComponent::new(&engine, component_bytes(interface)).unwrap();
    let instance = linker
        .instantiate_async(&mut store, &component)
        .await
        .unwrap();
    let run = instance
        .get_typed_func::<(Resource<wit::Upload>, u32), ()>(&mut store, "run")
        .unwrap();
    if mode == 2 {
        {
            let mut call = Box::pin(run.call_async(&mut store, (Resource::new_own(rep), mode)));
            poll_fn(|cx| {
                for _ in 0..64 {
                    match call.as_mut().poll(cx) {
                        Poll::Pending if entered.load(Ordering::SeqCst) => return Poll::Ready(()),
                        Poll::Pending => {}
                        Poll::Ready(_) => panic!("the controlled host wait did not remain pending"),
                    }
                }
                panic!("the controlled host wait was never entered")
            })
            .await;
            assert_eq!(*events.lock().unwrap(), ["wait-entered"]);
            drop(call);
        }
        events.lock().unwrap().push("call-abandoned");
    } else {
        let result = run
            .call_async(&mut store, (Resource::new_own(rep), mode))
            .await;
        if mode == 0 {
            result.expect("canonical drop should return");
        } else if mode == 1 {
            let error = result.expect_err("the guest trap must fail the call");
            assert_eq!(
                error.downcast_ref::<wasmtime::Trap>(),
                Some(&wasmtime::Trap::UnreachableCodeReached)
            );
        } else {
            let error = result.expect_err("the live canonical borrow must reject drop");
            assert!(
                error
                    .chain()
                    .any(|cause| cause.to_string() == "cannot remove owned resource while borrowed"),
                "resource-drop must fail specifically on the live borrow: {error:?}"
            );
        }
        events.lock().unwrap().push("call-returned");
    }
    drop(store);
    events.lock().unwrap().push("store-dropped");
    let observed = events.lock().unwrap().clone();
    println!("diagnostic interface={interface} mode={mode} events={observed:?}");
    observed
}

fn position(events: &[&str], expected: &str) -> usize {
    assert_eq!(
        events.iter().filter(|event| **event == expected).count(),
        1,
        "each observed transition must occur exactly once: {events:?}"
    );
    events.iter().position(|event| *event == expected).unwrap()
}

#[tokio::test]
async fn real_canonical_upload_drop_currently_runs_before_the_guest_marker() {
    for interface in [super::STREAMING_HTTP_CAPABILITY, UPLOAD_WINDOW_INTERFACE] {
        assert_eq!(
            diagnostic(0, interface).await,
            [
                "upload-drop",
                "guest-marker",
                "call-returned",
                "store-dropped"
            ],
            "canonical drop must be observed for the selected linker resource"
        );
    }
}

#[tokio::test]
async fn trapped_upload_is_retained_until_the_actual_store_drops() {
    for interface in [super::STREAMING_HTTP_CAPABILITY, UPLOAD_WINDOW_INTERFACE] {
        assert_eq!(
            diagnostic(1, interface).await,
            [
                "guest-marker",
                "call-returned",
                "upload-drop",
                "store-dropped"
            ]
        );
    }
}

#[tokio::test]
async fn abandoned_wait_retains_the_upload_until_the_actual_store_drops() {
    for interface in [super::STREAMING_HTTP_CAPABILITY, UPLOAD_WINDOW_INTERFACE] {
        let events = diagnostic(2, interface).await;
        assert_eq!(events.len(), 5);
        let entered = position(&events, "wait-entered");
        let abandoned = position(&events, "call-abandoned");
        let wait_dropped = position(&events, "wait-dropped");
        let upload_dropped = position(&events, "upload-drop");
        let store_dropped = position(&events, "store-dropped");
        assert!(entered < abandoned && entered < wait_dropped);
        assert!(abandoned < upload_dropped && wait_dropped < upload_dropped);
        assert!(upload_dropped < store_dropped);
    }
}

#[tokio::test]
async fn real_pending_canonical_borrow_rejects_drop_before_the_upload_destructor() {
    for interface in [super::STREAMING_HTTP_CAPABILITY, UPLOAD_WINDOW_INTERFACE] {
        let events = diagnostic(3, interface).await;
        assert_eq!(events.len(), 6);
        let entered = position(&events, "borrow-entered");
        let marker = position(&events, "guest-marker");
        let returned = position(&events, "call-returned");
        let borrow_dropped = position(&events, "borrow-dropped");
        let upload_dropped = position(&events, "upload-drop");
        let store_dropped = position(&events, "store-dropped");
        assert!(entered < marker && marker < returned && marker < borrow_dropped);
        assert!(returned < upload_dropped && borrow_dropped < upload_dropped);
        assert!(upload_dropped < store_dropped);
    }
}
