//! Bounded regressions for RUSTSEC-2026-0315 and RUSTSEC-2026-0316.
use std::borrow::Cow;

use super::super::WasmtimeConfig;
use wasm_encoder::{
    Alias, BlockType, CanonicalFunctionSection, CanonicalOption, Catch, CodeSection,
    ComponentAliasSection, ComponentExportKind, ComponentExportSection, ComponentTypeSection,
    ComponentValType, ElementSection, Elements, ExportKind, ExportSection, Function,
    FunctionSection, InstanceSection, Instruction, MemArg, MemorySection, MemoryType, ModuleArg,
    ModuleSection, PrimitiveValType, TagKind, TagSection, TagType, TypeSection, ValType,
};
use wasmtime::{component, Config, Engine, Instance, Module, Store};

fn engine(java: bool) -> Engine {
    let policy = WasmtimeConfig {
        guest_languages: crate::GuestLanguageProfiles {
            java_guest: java,
            ..Default::default()
        },
        fuel_async_yield_interval: java.then_some(10_000),
        ..WasmtimeConfig::default()
    };
    let mut config = Config::new();
    policy.apply_engine(&mut config).unwrap();
    Engine::new(&config).unwrap()
}

fn fuel_module(exceptional: bool) -> Vec<u8> {
    let mut module = wasm_encoder::Module::new();
    let mut types = TypeSection::new();
    types.ty().function([], []);
    module.section(&types);
    let mut functions = FunctionSection::new();
    functions.function(0).function(0);
    module.section(&functions);
    if exceptional {
        let mut tags = TagSection::new();
        tags.tag(TagType {
            kind: TagKind::Exception,
            func_type_idx: 0,
        });
        module.section(&tags);
    }
    let mut exports = ExportSection::new();
    exports.export("run", ExportKind::Func, 1);
    module.section(&exports);
    if !exceptional {
        let mut elements = ElementSection::new();
        elements.declared(Elements::Functions(Cow::Borrowed(&[0])));
        module.section(&elements);
    }
    let mut target = Function::new([]);
    // Fixed work, not a loop: a regressed runtime still terminates immediately.
    for _ in 0..64 {
        target.instruction(&Instruction::I32Const(1));
        target.instruction(&Instruction::Drop);
    }
    if exceptional {
        target.instruction(&Instruction::Throw(0));
    }
    target.instruction(&Instruction::End);
    let mut caller = Function::new([]);
    if exceptional {
        caller.instruction(&Instruction::Block(BlockType::Empty));
        caller.instruction(&Instruction::TryTable(
            BlockType::Empty,
            Cow::Borrowed(&[Catch::One { tag: 0, label: 0 }]),
        ));
        caller.instruction(&Instruction::Call(0));
        caller.instruction(&Instruction::End);
        caller.instruction(&Instruction::End);
    } else {
        caller.instruction(&Instruction::RefFunc(0));
        caller.instruction(&Instruction::CallRef(0));
    }
    caller.instruction(&Instruction::End);
    let mut code = CodeSection::new();
    code.function(&target).function(&caller);
    module.section(&code);
    module.finish()
}

fn assert_callee_fuel_is_retained(exceptional: bool) {
    let engine = engine(exceptional);
    let module = Module::new(&engine, fuel_module(exceptional)).unwrap();
    let mut store = Store::new(&engine, ());
    store.set_fuel(10_000).unwrap();
    store.set_epoch_deadline(1);
    let instance = Instance::new(&mut store, &module, &[]).unwrap();
    let run = instance
        .get_typed_func::<(), ()>(&mut store, "run")
        .unwrap();
    let before = store.get_fuel().unwrap();
    run.call(&mut store, ()).unwrap();
    let consumed = before - store.get_fuel().unwrap();
    assert!(consumed >= 64, "Callee fuel was lost on return: {consumed}");
}

#[test]
fn call_ref_retains_callee_fuel_in_the_ordinary_engine() {
    assert_callee_fuel_is_retained(false);
}

#[test]
fn exception_return_retains_callee_fuel_in_the_java_engine() {
    assert_callee_fuel_is_retained(true);
}

fn record_module() -> wasm_encoder::Module {
    let mut module = wasm_encoder::Module::new();
    let mut types = TypeSection::new();
    types.ty().function([], [ValType::I32]);
    module.section(&types);
    let mut functions = FunctionSection::new();
    functions.function(0);
    module.section(&functions);
    let mut memories = MemorySection::new();
    memories.memory(MemoryType {
        minimum: 1,
        maximum: Some(1),
        memory64: false,
        shared: false,
        page_size_log2: None,
    });
    module.section(&memories);
    let mut exports = ExportSection::new();
    exports.export("run", ExportKind::Func, 0);
    exports.export("memory", ExportKind::Memory, 0);
    module.section(&exports);
    let mut function = Function::new([]);
    for (offset, value) in [(1024, 0), (1028, 10)] {
        function.instruction(&Instruction::I32Const(offset));
        function.instruction(&Instruction::I32Const(value));
        function.instruction(&Instruction::I32Store(MemArg {
            offset: 0,
            align: 2,
            memory_index: 0,
        }));
    }
    function.instruction(&Instruction::I32Const(1024));
    function.instruction(&Instruction::End);
    let mut code = CodeSection::new();
    code.function(&function);
    module.section(&code);
    module
}

fn record_component() -> Vec<u8> {
    let mut component = wasm_encoder::Component::new();
    component.section(&ModuleSection(&record_module()));
    let mut instances = InstanceSection::new();
    instances.instantiate(0, [] as [(&str, ModuleArg); 0]);
    component.section(&instances);
    let mut aliases = ComponentAliasSection::new();
    for (kind, name) in [(ExportKind::Func, "run"), (ExportKind::Memory, "memory")] {
        aliases.alias(Alias::CoreInstanceExport {
            instance: 0,
            kind,
            name,
        });
    }
    component.section(&aliases);
    let names = ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j"];
    let mut types = ComponentTypeSection::new();
    types
        .defined_type()
        .record(names.map(|name| (name, PrimitiveValType::Bool)));
    component.section(&types);
    let mut exports = ComponentExportSection::new();
    exports.export("record", ComponentExportKind::Type, 0, None);
    component.section(&exports);
    let mut types = ComponentTypeSection::new();
    types.defined_type().list(ComponentValType::Type(1));
    types
        .function()
        .params([] as [(&str, ComponentValType); 0])
        .result(Some(ComponentValType::Type(2)));
    component.section(&types);
    let mut canonical = CanonicalFunctionSection::new();
    canonical.lift(0, 3, [CanonicalOption::Memory(0)]);
    component.section(&canonical);
    let mut exports = ComponentExportSection::new();
    exports.export("run", ComponentExportKind::Func, 0, None);
    component.section(&exports);
    component.finish()
}

#[test]
fn dynamic_record_lifting_charges_host_allocations_before_acceptance() {
    let engine = engine(false);
    let component = component::Component::new(&engine, record_component()).unwrap();
    let linker = component::Linker::<()>::new(&engine);
    for budget in [1_000, 100_000] {
        let mut store = Store::new(&engine, ());
        store.set_fuel(10_000).unwrap();
        store.set_epoch_deadline(1);
        store.set_hostcall_fuel(budget);
        let instance = linker.instantiate(&mut store, &component).unwrap();
        let run = instance.get_func(&mut store, "run").unwrap();
        let mut results = [component::Val::Bool(false)];
        let outcome = run.call(&mut store, &[], &mut results);
        if budget == 1_000 {
            assert!(
                outcome.is_err(),
                "Nested record allocations must exhaust the small host budget"
            );
        } else {
            outcome.unwrap();
            let component::Val::List(records) = &results[0] else {
                panic!("Expected a record list")
            };
            assert_eq!(records.len(), 10);
            for record in records {
                let component::Val::Record(fields) = record else {
                    panic!("Expected a record")
                };
                assert_eq!(fields.len(), 10);
            }
        }
    }
}

#[test]
fn fixed_length_lists_remain_outside_the_closed_engine_profile() {
    let mut bytes = wasm_encoder::Component::new();
    let mut types = ComponentTypeSection::new();
    types
        .defined_type()
        .fixed_length_list(PrimitiveValType::U8, 4);
    bytes.section(&types);
    for java in [false, true] {
        assert!(component::Component::new(&engine(java), bytes.as_slice()).is_err());
    }
}
