use wasmtime::component::{Component, Linker, Val};
use wasmtime::{Config, Engine, Store};

use super::{bytes, CHECKSUM, CONTRACT, DIRTY_LOG, LOG};

#[test]
#[ignore = "requires the engine memory component built by tools/validate_contracts.sh"]
fn unchanged_instance_detects_dirty_memory_instead_of_masking_it_with_initialization() {
    let mut config = Config::new();
    config.wasm_component_model(true).consume_fuel(true);
    let engine = Engine::new(&config).unwrap();
    let component = Component::new(&engine, bytes()).unwrap();
    let mut linker = Linker::<u32>::new(&engine);
    linker
        .instance(LOG)
        .unwrap()
        .func_new("write", |mut store, _, parameters, results| {
            assert_eq!(parameters.len(), 3);
            assert!(matches!(&parameters[0], Val::Enum(level) if level == "info"));
            assert!(matches!(&parameters[1], Val::String(message) if message == DIRTY_LOG));
            assert!(matches!(&parameters[2], Val::List(fields) if fields.is_empty()));
            *store.data_mut() += 1;
            results[0] = Val::Result(Ok(Some(Box::new(Val::Bool(true)))));
            Ok(())
        })
        .unwrap();
    // This negative control deliberately reuses one Store AND one instance.
    // Its second call must expose the dirty bytes without emitting a dirty log.
    let mut store = Store::new(&engine, 0);
    store.set_fuel(100_000_000).unwrap();
    let instance = linker.instantiate(&mut store, &component).unwrap();
    let (_, interface) = instance.get_export(&mut store, None, CONTRACT).unwrap();
    let (_, index) = instance
        .get_export(&mut store, Some(&interface), "run")
        .unwrap();
    let function = instance.get_func(&mut store, index).unwrap();
    let input = [Val::Enum("success".to_owned())];
    let mut output = [Val::U32(0)];
    function.call(&mut store, &input, &mut output).unwrap();
    assert!(matches!(output[0], Val::U32(CHECKSUM)));
    assert_eq!(*store.data(), 1);
    function.call(&mut store, &input, &mut output).unwrap();
    assert!(matches!(output[0], Val::U32(4_294_967_041)));
    assert_eq!(*store.data(), 1);
}
