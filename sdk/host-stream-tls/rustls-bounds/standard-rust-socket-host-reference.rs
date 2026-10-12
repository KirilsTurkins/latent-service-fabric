use wasmtime::{Config, Engine, Instance, Module, Store, StoreLimits, StoreLimitsBuilder};
fn main() {
    let mut config = Config::new();
    config.consume_fuel(true);
    let engine = Engine::new(&config).unwrap();
    let module = Module::from_file(&engine, std::env::args().nth(1).unwrap()).unwrap();
    let import_count = module.imports().count();
    assert_eq!(import_count, 0);
    let limits: StoreLimits = StoreLimitsBuilder::new().memory_size(67_108_864).instances(1).build();
    let mut store = Store::new(&engine, limits);
    store.limiter(|limits| limits);
    store.set_fuel(100_000).unwrap();
    let instance = Instance::new(&mut store, &module, &[]).unwrap();
    let result = instance.get_typed_func::<(), u32>(&mut store, "connect_status").unwrap().call(&mut store, ()).unwrap();
    println!("{{\"importCount\":{},\"status\":{},\"fuelRemaining\":{}}}", import_count, result, store.get_fuel().unwrap());
    assert_eq!(result, 1);
}
