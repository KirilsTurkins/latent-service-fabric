//! Actual component memory observations; synthetic reply, never node admission.
use super::{Component, Engine, Linker, Store, StoreLimits, StoreLimitsBuilder, Val};
use wasmtime::ResourceLimiter;

const MAXIMUM: usize = 128 * 1024 * 1024;

struct Memory {
    limits: StoreLimits,
    bytes: usize,
    pending: usize,
}

impl ResourceLimiter for Memory {
    fn memory_growing(
        &mut self,
        current: usize,
        desired: usize,
        maximum: Option<usize>,
    ) -> wasmtime::Result<bool> {
        self.pending = 0;
        let growth = desired.saturating_sub(current);
        let total = self
            .bytes
            .checked_add(growth)
            .expect("bounded diagnostic memory");
        if total > MAXIMUM {
            return Err(wasmtime::Error::msg("diagnostic aggregate memory ceiling"));
        }
        let allowed = self.limits.memory_growing(current, desired, maximum)?;
        if allowed {
            self.bytes = total;
            self.pending = growth;
        }
        Ok(allowed)
    }

    fn memory_grow_failed(&mut self, error: wasmtime::Error) -> wasmtime::Result<()> {
        self.bytes -= self.pending;
        self.pending = 0;
        self.limits.memory_grow_failed(error)
    }

    fn table_growing(
        &mut self,
        current: usize,
        desired: usize,
        maximum: Option<usize>,
    ) -> wasmtime::Result<bool> {
        self.pending = 0;
        self.limits.table_growing(current, desired, maximum)
    }
}

pub(super) async fn run(
    engine: &Engine,
    component: &Component,
    caller: bool,
) -> wasmtime::Result<()> {
    let mut linker = Linker::new(engine);
    if caller {
        linker
            .instance("latent:service/invoke@0.1.0")?
            .func_new_concurrent("call", |_, _, _, output| {
                Box::pin(async move {
                    output[0] = Val::Variant(
                        "success".into(),
                        Some(Box::new(Val::Record(vec![
                            (
                                "payload".into(),
                                Val::List(b"[42]".iter().copied().map(Val::U8).collect()),
                            ),
                            (
                                "media-type".into(),
                                Val::String("application/vnd.latent.wit-values.v1+json".into()),
                            ),
                            ("metadata".into(), Val::List(vec![])),
                        ]))),
                    );
                    Ok(())
                })
            })?;
    }
    for ordinal in 0..3 {
        let memory = Memory {
            limits: StoreLimitsBuilder::new().memory_size(MAXIMUM).build(),
            bytes: 0,
            pending: 0,
        };
        let mut store = Store::new(engine, memory);
        store.limiter(|memory| memory);
        store.set_fuel(1_000_000_000)?;
        let instance = linker.instantiate_async(&mut store, component).await?;
        let initial = store.data().bytes;
        let contract = if caller {
            "tests:caller/api@1.0.0"
        } else {
            "tests:local/api@1.0.0"
        };
        let (_, interface) = instance
            .get_export(&mut store, None, contract)
            .expect("service API");
        let (_, index) = instance
            .get_export(
                &mut store,
                Some(&interface),
                if caller { "run" } else { "answer" },
            )
            .expect("service function");
        let function = instance.get_func(&mut store, index).expect("callable");
        let input = if caller {
            vec![Val::U32(0), Val::String(String::new()), Val::U64(0)]
        } else {
            vec![]
        };
        let mut output = [Val::Bool(false)];
        function.call_async(&mut store, &input, &mut output).await?;
        assert_eq!(output, [if caller { Val::U64(42) } else { Val::U32(42) }]);
        let peak = store.data().bytes;
        println!("diagnostic service caller={caller} case={ordinal} initialMemoryBytes={initial} peakLinearMemoryBytes={peak} fuel={}",
            1_000_000_000 - store.get_fuel()?);
        assert!(peak <= MAXIMUM);
        drop(store);
    }
    Ok(())
}
