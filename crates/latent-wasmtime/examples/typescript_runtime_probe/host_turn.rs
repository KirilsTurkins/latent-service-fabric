//! Finite canonical scheduler control. This is test-only and does not insert a
//! yield into the TypeScript engine or claim signed/provider qualification.
use std::{
    future::Future,
    pin::Pin,
    sync::{Arc, Mutex},
    task::{Context, Poll},
    time::Duration,
};
use wasmtime::{
    component::{Component, Linker},
    Engine, Store, StoreLimits, StoreLimitsBuilder,
};

#[path = "host_turn_component.rs"]
mod component;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
struct Sample {
    polls: u32,
    event: u32,
    drops: u32,
}

#[derive(Default)]
struct Counts {
    created: u32,
    polls: u32,
    dropped: u32,
    samples: [Option<Sample>; 5],
}

// This is the actual future supplied to Wasmtime, not a fabricated waitable.
// It requests a wake on its first poll. Wasmtime's inline first poll uses a
// no-op waker, then inserts the pending future into a host-future set which
// initially queues every new entry. In this isolated one-future control, that
// set poll is the second overall poll. This probes that finite insertion
// boundary, not an external readiness change or later network progress.
// Its original object stays alive after the first poll and counts its own Drop.
struct OncePending(Arc<Mutex<Counts>>);
impl Future for OncePending {
    type Output = wasmtime::Result<(u32,)>;

    fn poll(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Self::Output> {
        let poll = {
            let mut counts = self.0.lock().unwrap();
            counts.polls += 1;
            counts.polls
        };
        match poll {
            1 => {
                cx.waker().wake_by_ref();
                Poll::Pending
            }
            2 => Poll::Ready(Ok((42,))),
            _ => panic!("the same future was polled after completion"),
        }
    }
}
impl Drop for OncePending {
    fn drop(&mut self) {
        self.0.lock().unwrap().dropped += 1;
    }
}

pub(super) async fn run() -> wasmtime::Result<()> {
    // Match the relevant selected TypeScript component features explicitly;
    // this dedicated diagnostic engine is separate from every existing case.
    let mut config = wasmtime::Config::new();
    config
        .wasm_component_model(true)
        .wasm_component_model_async(true)
        .wasm_component_model_more_async_builtins(true)
        .wasm_component_model_threading(false)
        .wasm_component_model_async_stackful(false)
        .consume_fuel(true);
    let engine = Engine::new(&config)?;
    let mut completed = 0_u8;
    for asynchronous in [false, true] {
        for yielding in [false, true] {
            let bit = 1_u8 << ((u8::from(asynchronous) << 1) | u8::from(yielding));
            wasmtime::ensure!(completed & bit == 0, "duplicate canonical diagnostic case");
            case(&engine, asynchronous, yielding).await?;
            completed |= bit;
        }
    }
    wasmtime::ensure!(completed == 0b1111, "missing canonical diagnostic case");
    println!(
        "canonical host-future poll/yield controls passed; TypeScript and signed node not qualified"
    );
    Ok(())
}

async fn case(engine: &Engine, asynchronous: bool, yielding: bool) -> wasmtime::Result<()> {
    let component = Component::new(engine, component::bytes(asynchronous, yielding))?;
    let counts = Arc::new(Mutex::new(Counts::default()));
    let mut linker = Linker::new(engine);
    let host = Arc::clone(&counts);
    linker
        .root()
        .func_wrap_concurrent("read", move |_, (): ()| {
            host.lock().unwrap().created += 1;
            Box::pin(OncePending(Arc::clone(&host)))
        })?;
    let host = Arc::clone(&counts);
    linker
        .root()
        .func_wrap("observe", move |_, (turn, event): (u32, u32)| {
            let index = usize::try_from(turn)?;
            let mut counts = host.lock().unwrap();
            let sample = Sample {
                polls: counts.polls,
                event,
                drops: counts.dropped,
            };
            let place = counts
                .samples
                .get_mut(index)
                .ok_or_else(|| wasmtime::Error::msg("unexpected diagnostic turn"))?;
            wasmtime::ensure!(place.is_none(), "duplicate diagnostic turn");
            *place = Some(sample);
            Ok(())
        })?;
    let mut store = Store::new(engine, StoreLimitsBuilder::new().memory_size(65536).build());
    store.limiter(|limits: &mut StoreLimits| limits);
    store.set_fuel(1_000_000)?;
    let instance = linker.instantiate_async(&mut store, &component).await?;
    let run = instance.get_typed_func::<(), (u32,)>(&mut store, "run")?;
    let result = tokio::time::timeout(Duration::from_secs(2), run.call_async(&mut store, ()))
        .await
        .map_err(|_| wasmtime::Error::msg("canonical diagnostic exceeded bounded duration"))?;
    if asynchronous {
        wasmtime::ensure!(result? == (42,), "async diagnostic did not finish");
        // An acknowledged completion or cancellation must retire the actual
        // host Future before the containing Store itself is dropped.
        wasmtime::ensure!(
            counts.lock().unwrap().dropped == 1,
            "acknowledged host future still live before Store drop"
        );
    } else {
        let trap = result.expect_err("synchronous control must trap after finite observations");
        wasmtime::ensure!(
            trap.downcast_ref::<wasmtime::Trap>() == Some(&wasmtime::Trap::UnreachableCodeReached),
            "synchronous diagnostic trapped before its intended terminator"
        );
    }
    drop(store); // synchronous trap cleanup is checked after Store destruction
    let counts = counts.lock().unwrap();
    wasmtime::ensure!(
        counts.created == 1 && counts.dropped == 1,
        "the original host future was not created and dropped exactly once"
    );
    wasmtime::ensure!(
        counts.samples[0]
            == Some(Sample {
                polls: 1,
                event: 0,
                drops: 0
            }),
        "the host future was not initially pending and joined"
    );
    if asynchronous && yielding {
        wasmtime::ensure!(
            counts.polls == 2
                && counts
                    .samples
                    .iter()
                    .flatten()
                    .any(|s| s.polls == 2 && s.event == 1 && s.drops == 1)
                && counts
                    .samples
                    .iter()
                    .flatten()
                    .filter(|s| s.event == 1)
                    .count()
                    == 1,
            "yielding async task did not observe exactly one host completion"
        );
    } else {
        wasmtime::ensure!(
            counts.samples.iter().all(|sample| *sample
                == Some(Sample {
                    polls: 1,
                    event: 0,
                    drops: 0
                })),
            "non-yielding or synchronous task unexpectedly drove the host future"
        );
    }
    println!(
        "canonical host turn: async={asynchronous} yielding={yielding} samples={:?} original-drops=1",
        counts.samples
    );
    Ok(())
}
