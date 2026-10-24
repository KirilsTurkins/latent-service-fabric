//! Executes the actual splicer-emitted disposer with counter-double frees.
//! These controls prove preflight/order, never allocator/physical release.
use sha2::{Digest, Sha256};
use std::{path::Path, time::Instant};
use wasmtime::{Engine, Linker, Module, Store, StoreLimits, StoreLimitsBuilder, Val};

const CASES: [&str; 8] = [
    "invalid-active-tag",
    "overflowing-list-range",
    "misaligned-list",
    "zero-size-nonzero-pointer",
    "valid-empty-string",
    "valid-zero-stride-list",
    "nested-invalid-after-valid-child",
    "own-trap-before-container-free",
];
struct State {
    drops: u32,
    limits: StoreLimits,
}

pub(super) fn run(engine: &Engine, directory: &Path) -> wasmtime::Result<()> {
    let manifest = std::fs::read(directory.join("manifest.json"))?;
    wasmtime::ensure!(manifest.len() <= 32768, "backing-core-manifest-bound");
    let manifest_sha = Sha256::digest(&manifest)
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect::<String>();
    let rows: Vec<serde_json::Value> = serde_json::from_slice(&manifest)?;
    wasmtime::ensure!(rows.len() == CASES.len(), "backing-core-exact-case-set");
    let mut actual = std::fs::read_dir(directory)?
        .map(|entry| entry.map(|entry| entry.file_name().to_string_lossy().into_owned()))
        .collect::<Result<Vec<_>, _>>()?;
    let mut expected = vec!["manifest.json".to_owned()];
    expected.extend(
        CASES
            .iter()
            .enumerate()
            .map(|(index, name)| format!("{index:02}-{name}.wasm")),
    );
    actual.sort();
    expected.sort();
    wasmtime::ensure!(
        actual == expected,
        "backing-core-no-extra-or-missing-products"
    );
    for (which, name) in CASES.into_iter().enumerate() {
        let started = Instant::now();
        let file = format!("{which:02}-{name}.wasm");
        let row = &rows[which];
        let expected_return = if which == 7 {
            None
        } else {
            Some(u32::from(matches!(which, 4 | 5)))
        };
        wasmtime::ensure!(
            row.as_object().is_some_and(|value| value.len() == 8)
                && row["case"] == name
                && row["file"] == file
                && row["argument"] == 32
                && row["expectedReturn"] == serde_json::json!(expected_return)
                && row["expectedTrap"] == (which == 7)
                && row["expectedDoubleFreeReturns"] == 0
                && row["allocatorEvidence"] == false,
            "backing-core-manifest-contract"
        );
        let path = directory.join(&file);
        let metadata = path.symlink_metadata()?;
        wasmtime::ensure!(
            metadata.is_file()
                && !metadata.file_type().is_symlink()
                && metadata.len() <= 65536
                && row["bytes"].as_u64() == Some(metadata.len()),
            "backing-core-exact-module-bound"
        );
        let bytes = std::fs::read(path)?;
        let sha = Sha256::digest(&bytes)
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect::<String>();
        let module = Module::new(engine, &bytes)?;
        let mut linker = Linker::<State>::new(engine);
        linker.func_wrap(
            "tests:imports/io@1.0.0",
            "[resource-drop]connection",
            |mut caller: wasmtime::Caller<'_, State>, _handle: i32| -> wasmtime::Result<()> {
                caller.data_mut().drops += 1;
                wasmtime::bail!("backing-core-original-drop-refusal")
            },
        )?;
        let mut store = Store::new(
            engine,
            State {
                drops: 0,
                limits: StoreLimitsBuilder::new().memory_size(65536).build(),
            },
        );
        store.limiter(|state| &mut state.limits);
        store.set_fuel(1_000_000_000)?;
        let instance = linker.instantiate(&mut store, &module)?;
        let dispose = instance.get_typed_func::<i32, i32>(&mut store, "dispose")?;
        let result = dispose.call(&mut store, 32);
        let returned = if which == 7 {
            let error = result.expect_err("actual emitted OWN call must trap");
            wasmtime::ensure!(
                format!("{error:#}").contains("backing-core-original-drop-refusal"),
                "backing-core-wrong-trap"
            );
            None
        } else {
            let value = u32::try_from(result?)?;
            wasmtime::ensure!(
                Some(value) == expected_return,
                "backing-core-preflight-result"
            );
            Some(value)
        };
        // Direct host inspection of a standalone core global executes no new
        // guest call/root after a trap. This remains a counter double only.
        let counter = instance
            .get_global(&mut store, "free-returns")
            .ok_or_else(|| wasmtime::Error::msg("backing-core-counter-missing"))?;
        wasmtime::ensure!(
            matches!(counter.get(&mut store), Val::I32(0)),
            "backing-core-side-effect-before-complete-preflight-or-after-trap"
        );
        wasmtime::ensure!(
            store.data().drops == u32::from(which == 7),
            "backing-core-exact-drop-call"
        );
        let fuel = 1_000_000_000 - store.get_fuel()?;
        wasmtime::ensure!(
            started.elapsed().as_secs_f64() <= 20.0,
            "backing-core-case-deadline"
        );
        println!(
            "{}",
            serde_json::json!({"schemaVersion":"latent.typescript.backing-core-case.v1",
            "case":name,"index":which,"status":"passed","moduleBytes":bytes.len(),"moduleSha256":sha,
            "manifestSha256":manifest_sha,"returned":returned,"trapped":which==7,
            "doubleFreeReturns":0,"originalDropCalls":store.data().drops,"fuel":fuel,
            "allocatorEvidence":false,"guestRootReopened":false})
        );
    }
    Ok(())
}
