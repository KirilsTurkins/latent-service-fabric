//! Execute the actual compiled Rust pump with two independently held imports.
//! This is a guest adapter regression, not a signed-node or HTTP qualification.
use std::{
    future::{poll_fn, Future},
    sync::{
        atomic::{AtomicBool, AtomicUsize, Ordering},
        Arc, Mutex,
    },
    task::{Poll, Waker},
    time::Duration,
};
use wasmtime::{
    component::{Component, Linker},
    Config, Engine, Store,
};
#[derive(Default)]
struct Gate {
    ready: AtomicBool,
    polls: AtomicUsize,
    live: AtomicUsize,
    drops: AtomicUsize,
    waker: Mutex<Option<Waker>>,
    controller: Mutex<Option<Waker>>,
}
impl Gate {
    async fn wait(self: Arc<Self>) {
        struct Guard(Arc<Gate>);
        impl Drop for Guard {
            fn drop(&mut self) {
                self.0.live.fetch_sub(1, Ordering::SeqCst);
                self.0.drops.fetch_add(1, Ordering::SeqCst);
                self.0.waker.lock().unwrap().take();
            }
        }
        self.live.fetch_add(1, Ordering::SeqCst);
        let _guard = Guard(self.clone());
        poll_fn(|cx| {
            self.polls.fetch_add(1, Ordering::SeqCst);
            if let Some(waker) = self.controller.lock().unwrap().take() {
                waker.wake();
            }
            if self.ready.load(Ordering::SeqCst) {
                Poll::Ready(())
            } else {
                *self.waker.lock().unwrap() = Some(cx.waker().clone());
                Poll::Pending
            }
        })
        .await;
    }
    fn release(&self) {
        self.ready.store(true, Ordering::SeqCst);
        if let Some(waker) = self.waker.lock().unwrap().take() {
            waker.wake();
        }
    }
}
#[tokio::main(flavor = "current_thread")]
async fn main() -> wasmtime::Result<()> {
    let path = std::env::args_os()
        .nth(1)
        .expect("compiled pump component path");
    let mut config = Config::new();
    config
        .wasm_component_model_async(true)
        .concurrency_support(true)
        .consume_fuel(true);
    if std::env::args().any(|arg| arg == "--native-profile") {
        config
            .wasm_component_model_more_async_builtins(true)
            .wasm_component_model_threading(true)
            .wasm_component_model_async_stackful(true);
    }
    let engine = Engine::new(&config)?;
    let component = Component::from_file(&engine, path)?;
    let gates: Arc<[Arc<Gate>; 4]> = Arc::new(std::array::from_fn(|_| Arc::new(Gate::default())));
    let host_gates = gates.clone();
    let mut linker = Linker::<()>::new(&engine);
    linker
        .instance("latent:rust-http-pump-control/host@0.1.0")?
        .func_wrap_concurrent("wait", move |_, (key,): (u32,)| {
            let gate = host_gates
                .get(key as usize)
                .expect("finite probe key")
                .clone();
            Box::pin(async move {
                gate.wait().await;
                Ok(())
            })
        })?;
    let mut store = Store::new(&engine, ());
    store.set_fuel(1_000_000_000)?;
    let instance = linker.instantiate_async(&mut store, &component).await?;
    let run = instance.get_typed_func::<(u32,), (u32,)>(&mut store, "run")?;
    let retire = instance.get_typed_func::<(u32,), ()>(&mut store, "retire")?;
    let drain = instance.get_typed_func::<(), ()>(&mut store, "drain")?;
    let poke = instance.get_typed_func::<(), ()>(&mut store, "poke")?;
    tokio::time::timeout(
        Duration::from_secs(5),
        store.run_concurrent(async |access| {
            let mut first = Box::pin(run.call_concurrent(access, (0,)));
            let mut second = Box::pin(run.call_concurrent(access, (1,)));
            let mut second_returned = false;
            let mut third = Box::pin(run.call_concurrent(access, (2,)));
            let mut third_returned = false;
            let mut observation = Box::pin(poke.call_concurrent(access, ()));
            let mut observed = false;
            poll_fn(|cx| -> Poll<wasmtime::Result<()>> {
                for gate in gates.iter() {
                    *gate.controller.lock().unwrap() = Some(cx.waker().clone());
                }
                let first_poll = first.as_mut().poll(cx);
                if third_returned {
                    return first_poll.map(|result| {
                        assert_eq!(result?, (0,));
                        Ok(())
                    });
                }
                if second_returned {
                    assert!(
                        first_poll.is_pending(),
                        "original lost its hold before third completion"
                    );
                    match third.as_mut().poll(cx) {
                        Poll::Ready(value) => {
                            assert_eq!(value?, (2,));
                            assert!(!gates[0].ready.load(Ordering::SeqCst));
                            assert_eq!(gates[0].live.load(Ordering::SeqCst), 1);
                            assert_eq!(gates[2].live.load(Ordering::SeqCst), 0);
                            third_returned = true;
                            gates[0].release();
                        }
                        Poll::Pending => {
                            if gates[2].polls.load(Ordering::SeqCst) != 0 {
                                gates[2].release();
                            }
                        }
                    }
                    return Poll::Pending;
                }
                assert!(
                    first_poll.is_pending(),
                    "held caller resumed before its actual completion"
                );
                match second.as_mut().poll(cx) {
                    Poll::Ready(value) => {
                        assert_eq!(value?, (1,));
                        assert!(!gates[0].ready.load(Ordering::SeqCst));
                        assert_eq!(gates[0].live.load(Ordering::SeqCst), 1);
                        assert_eq!(gates[1].live.load(Ordering::SeqCst), 0);
                        second_returned = true;
                        cx.waker().wake_by_ref();
                    }
                    Poll::Pending => {
                        if gates[0].polls.load(Ordering::SeqCst) != 0
                            && gates[1].polls.load(Ordering::SeqCst) != 0
                        {
                            if !observed {
                                match observation.as_mut().poll(cx) {
                                    Poll::Ready(result) => {
                                        result?;
                                        observed = true;
                                    }
                                    Poll::Pending => return Poll::Pending,
                                }
                            }
                            gates[1].release();
                        }
                    }
                }
                Poll::Pending
            })
            .await
        }),
    )
    .await???;
    for gate in &gates[..3] {
        assert_eq!(gate.live.load(Ordering::SeqCst), 0);
        assert_eq!(gate.drops.load(Ordering::SeqCst), 1);
    }
    tokio::time::timeout(Duration::from_secs(5), retire.call_async(&mut store, (3,))).await??;
    assert!(!gates[3].ready.load(Ordering::SeqCst));
    assert_eq!(gates[3].live.load(Ordering::SeqCst), 1);
    assert_eq!(gates[3].drops.load(Ordering::SeqCst), 0);
    tokio::time::timeout(Duration::from_secs(5), drain.call_async(&mut store, ())).await??;
    assert_eq!(gates[3].live.load(Ordering::SeqCst), 0);
    assert_eq!(gates[3].drops.load(Ordering::SeqCst), 1);
    store.assert_concurrent_state_empty();
    assert!(store.get_fuel()? < 1_000_000_000);
    println!(
        "actual compiled pump: two sequential siblings before held release; deferred cancellation; empty engine state"
    );
    Ok(())
}
