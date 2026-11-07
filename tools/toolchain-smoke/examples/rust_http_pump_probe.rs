//! Executed callback/wakeup control, not signed application qualification.
#![cfg(target_arch = "wasm32")]
wit_bindgen::generate!({
    inline: r#"
        package latent:rust-http-pump-control@0.1.0;
        interface host { wait: async func(key: u32); }
        world control {
            import host;
            export run: async func(key: u32) -> u32;
            export retire: async func(key: u32);
            export drain: async func();
        }
    "#,
});
#[path = "../../../sdk/wasi-http-runtime/pump.rs"]
mod pump;
use std::{cell::{Cell, RefCell}, future::Future, pin::Pin, rc::Rc, task::{Context, Poll}};
type Work = Pin<Box<dyn Future<Output = ()>>>;
struct Operation {
    work: RefCell<Option<Work>>, started: Cell<bool>, ready: Cell<bool>,
}
impl Operation {
    fn new(key: u32) -> Rc<Self> {
        let value = Rc::new(Self {
            work: RefCell::new(Some(Box::pin(latent::rust_http_pump_control::host::wait(key)))),
            started: Cell::new(false), ready: Cell::new(false),
        });
        let operation: Rc<dyn pump::Progress> = value.clone();
        pump::Pump::track(&operation);
        value
    }
}
impl pump::Progress for Operation {
    fn pending(&self) -> bool { self.work.borrow().is_some() }
    fn progress(&self, cx: &mut Context<'_>) {
        let Some(mut work) = self.work.borrow_mut().take() else { return };
        self.started.set(true);
        match work.as_mut().poll(cx) {
            Poll::Pending => *self.work.borrow_mut() = Some(work),
            Poll::Ready(()) => self.ready.set(true),
        }
    }
}
impl pump::Readiness for Operation { fn ready(&self) -> bool { self.ready.get() } }
impl Drop for Operation {
    fn drop(&mut self) {
        if let Some(work) = self.work.get_mut().take() { pump::Pump::retire(move || drop(work)); }
    }
}
struct Started(Rc<Operation>);
impl pump::Readiness for Started { fn ready(&self) -> bool { self.0.started.get() } }
struct Control;
impl Guest for Control {
    async fn run(key: u32) -> u32 {
        let operation = Operation::new(key);
        let source: Rc<dyn pump::Readiness> = operation.clone();
        assert_eq!(pump::Pump::current().poll(&[source]).await, vec![0]);
        assert!(operation.ready.get()); key
    }
    async fn retire(key: u32) {
        let operation = Operation::new(key);
        let source: Rc<dyn pump::Readiness> = Rc::new(Started(operation.clone()));
        pump::Pump::current().poll(&[source]).await;
        assert!(!operation.ready.get()); drop(operation);
    }
    async fn drain() { pump::Pump::current().drain_retired().await; }
}
export!(Control);
