#![cfg(target_arch = "wasm32")]

mod scope;

use std::cell::Cell;
use std::future::Future;
use std::pin::Pin;
use std::rc::Rc;
use std::task::{Context, Poll};
use std::sync::atomic::{AtomicBool, Ordering};

static ENTERED: AtomicBool = AtomicBool::new(false);

wit_bindgen::generate!({
    path: "../../research/invocation-concurrency/wit",
    world: "research:concurrency/probe@0.1.0",
});

use research::concurrency::host;
use scope::{Task, YieldOnce, MAX_TASKS, TASK_LIMIT};

struct Frame {
    id: u32,
    future: Task<'static>,
}

impl Future for Frame {
    type Output = Result<u32, u32>;
    fn poll(mut self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Self::Output> {
        host::event(1, self.id);
        self.future.as_mut().poll(cx)
    }
}

impl Drop for Frame {
    fn drop(&mut self) {
        host::event(2, self.id);
    }
}

fn frame(id: u32, future: Task<'static>) -> Task<'static> {
    host::event(0, id);
    Box::pin(Frame { id, future })
}

fn summarize(results: Vec<Result<u32, u32>>) -> u64 {
    // Preserve every error: each task gets a bit in the upper 32 bits.
    results.into_iter().enumerate().fold(0, |sum, (i, result)| {
        match result {
            Ok(value) => sum + u64::from(value),
            Err(_) => sum | (1_u64 << (32 + i)),
        }
    })
}

struct Capsule;
impl exports::research::concurrency::api::Guest for Capsule {
    async fn run(mode: u32, tasks: u32) -> u64 {
        assert!(!ENTERED.swap(true, Ordering::Relaxed), "Store static state leaked");
        // Check BEFORE allocating frames or dispatching any host operation.
        if tasks as usize > MAX_TASKS {
            return u64::from(TASK_LIMIT);
        }
        match mode {
            0 => {
                let mut values = Vec::new();
                for id in 0..tasks {
                    values.push(frame(id, Box::pin(host::wait(id))).await);
                }
                summarize(values)
            }
            1 => {
                let tasks = (0..tasks)
                    .map(|id| frame(id, Box::pin(host::wait(id))))
                    .collect();
                summarize(scope::join(tasks).await.unwrap())
            }
            2 => {
                // Real unsupported std library API, not a fabricated host error.
                std::thread::spawn(|| 1_u64).join().unwrap()
            }
            3 => {
                // Counterexample to implementing Thread.start by calling run.
                // The child waits for initialization performed AFTER start returns.
                let ready = Cell::new(false);
                host::event(3, 0);
                while !std::hint::black_box(ready.get()) {
                    std::hint::spin_loop();
                }
                ready.set(true);
                1
            }
            4 => {
                // Same dependency with genuine cooperative progress, no threads.
                let ready = Rc::new(Cell::new(false));
                let child = ready.clone();
                let tasks: Vec<Task<'static>> = vec![
                    frame(0, Box::pin(async move {
                        while !child.get() {
                            YieldOnce::default().await;
                        }
                        Ok(1)
                    })),
                    frame(1, Box::pin(async move {
                        ready.set(true);
                        Ok(2)
                    })),
                ];
                summarize(scope::join(tasks).await.unwrap())
            }
            5 | 6 => {
                // Equal arithmetic work; mode 6 adds stackless scheduling.
                if mode == 5 {
                    let mut result = 0_u64;
                    for id in 0..tasks {
                        for _ in 0..256 {
                            result += u64::from(std::hint::black_box(id + 1));
                        }
                    }
                    result
                } else {
                    let tasks: Vec<Task<'static>> = (0..tasks)
                        .map(|id| {
                            Box::pin(async move {
                                let mut result = 0;
                                for _ in 0..256 {
                                    result += std::hint::black_box(id + 1);
                                    YieldOnce::default().await;
                                }
                                Ok(result)
                            }) as Task<'static>
                        })
                        .collect();
                    summarize(scope::join(tasks).await.unwrap())
                }
            }
            _ => panic!("unknown research mode"),
        }
    }
}
export!(Capsule);
