//! Real execution of the exact old/current closed adapter; no host filesystem.
use wasmtime::{
    Config, Engine, Extern, Instance, Memory, MemoryType, Module, Store, StoreLimitsBuilder,
};

fn adapter(engine: &Engine, variable: &str) -> (Store<wasmtime::StoreLimits>, Instance, Memory) {
    let bytes = std::fs::read(std::env::var_os(variable).expect("compile the exact owned adapter"))
        .unwrap();
    assert!(bytes.len() <= 65_536);
    let module = Module::new(engine, bytes).unwrap();
    let imports = module.imports().collect::<Vec<_>>();
    assert_eq!(imports.len(), 1);
    assert_eq!(imports[0].module(), "env");
    assert_eq!(imports[0].name(), "memory");
    assert!(matches!(imports[0].ty(), wasmtime::ExternType::Memory(_)));
    let limits = StoreLimitsBuilder::new()
        .memory_size(65_536)
        .table_elements(0)
        .instances(1)
        .memories(1)
        .build();
    let mut store = Store::new(engine, limits);
    store.limiter(|limit| limit);
    store.set_fuel(10_000).unwrap();
    let memory = Memory::new(&mut store, MemoryType::new(1, Some(1))).unwrap();
    let instance = Instance::new(&mut store, &module, &[Extern::Memory(memory)]).unwrap();
    (store, instance, memory)
}

#[test]
#[ignore = "requires the two exact wasm-tools-compiled closed Go adapter inputs"]
fn exact_closed_path_open_is_enosys_without_changing_discovery_or_other_authority() {
    let mut config = Config::new();
    config.consume_fuel(true);
    let engine = Engine::new(&config).unwrap();
    for (variable, expected) in [
        ("LSF_GO_CLOSED_ADAPTER_OLD", 76),
        ("LSF_GO_CLOSED_ADAPTER_CURRENT", 52),
    ] {
        let (mut store, instance, memory) = adapter(&engine, variable);
        let open = instance
            .get_typed_func::<(i32, i32, i32, i32, i32, i64, i64, i32, i32), i32>(
                &mut store,
                "path_open",
            )
            .unwrap();
        for flags in [0, 1, 5, 9] {
            assert_eq!(
                open.call(&mut store, (-1, 1, 0, 32, flags, 0, 0, 0, 64))
                    .unwrap(),
                expected
            );
        }
        let preopen = instance
            .get_typed_func::<(i32, i32), i32>(&mut store, "fd_prestat_get")
            .unwrap();
        assert_eq!(preopen.call(&mut store, (3, 0)).unwrap(), 8);
        let mkdir = instance
            .get_typed_func::<(i32, i32, i32), i32>(&mut store, "path_create_directory")
            .unwrap();
        assert_eq!(mkdir.call(&mut store, (-1, 0, 32)).unwrap(), 76);
        let socket = instance
            .get_typed_func::<(i32, i32), i32>(&mut store, "sock_shutdown")
            .unwrap();
        assert_eq!(socket.call(&mut store, (3, 0)).unwrap(), 76);
        let read = instance
            .get_typed_func::<(i32, i32, i32, i32), i32>(&mut store, "fd_read")
            .unwrap();
        assert_eq!(read.call(&mut store, (3, 0, 0, 64)).unwrap(), 8);
        assert!(memory.data(&store).iter().all(|byte| *byte == 0));
        assert!(store.get_fuel().unwrap() < 10_000);
        println!(
            "GO_CLOSED_ADAPTER_CASE {}",
            serde_json::json!({"pathOpen":expected,"preopen":8,"mkdir":76,"socket":76,"read":8,"memoryBytes":65_536})
        );
    }
}
