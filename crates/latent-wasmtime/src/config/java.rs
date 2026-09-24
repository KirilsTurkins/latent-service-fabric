//! Closed Java exception profile; the Java collector itself uses linear memory.
use latent_core::PlatformError;

use super::{invalid_config, InstanceAllocator, WasmtimeConfig};

pub(crate) const JAVA_EXCEPTION_HEAP_BYTES: usize = 4 * 1024 * 1024;
pub(super) const JAVA_EXCEPTION_HEAP_INITIAL_BYTES: u64 = 64 * 1024;

impl WasmtimeConfig {
    /// Installs engine support without increasing any operator resource budget.
    pub fn install_java_guest(&mut self) {
        self.java_guest = true;
    }

    pub(super) fn validate_java(&self) -> Result<(), PlatformError> {
        if self.java_guest
            && (self.instance_allocator != InstanceAllocator::OnDemand
                || self.angular_renderer
                || self.maximum_memory_bytes <= JAVA_EXCEPTION_HEAP_BYTES as u64
                || self.fuel_async_yield_interval.is_none())
        {
            return Err(invalid_config());
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::DispatchMode;
    use wasmtime::{component, Config, Engine, Module, Store};

    fn typed_function_component() -> Vec<u8> {
        use wasm_encoder::*;
        let mut module = wasm_encoder::Module::new();
        let mut types = TypeSection::new();
        types.ty().function([], [ValType::I32]);
        module.section(&types);
        let mut functions = FunctionSection::new();
        functions.function(0).function(0);
        module.section(&functions);
        let mut exports = ExportSection::new();
        exports.export("run", ExportKind::Func, 1);
        module.section(&exports);
        let mut elements = ElementSection::new();
        elements.declared(Elements::Functions(std::borrow::Cow::Borrowed(&[0])));
        module.section(&elements);
        let mut answer = Function::new([]);
        answer.instruction(&Instruction::I32Const(42));
        answer.instruction(&Instruction::End);
        let mut run = Function::new([]);
        run.instruction(&Instruction::RefFunc(0));
        run.instruction(&Instruction::CallRef(0));
        run.instruction(&Instruction::End);
        let mut code = CodeSection::new();
        code.function(&answer).function(&run);
        module.section(&code);
        let mut component = wasm_encoder::Component::new();
        component.section(&ModuleSection(&module));
        let mut instances = InstanceSection::new();
        instances.instantiate(0, [] as [(&str, ModuleArg); 0]);
        component.section(&instances);
        let mut aliases = ComponentAliasSection::new();
        aliases.alias(Alias::CoreInstanceExport {
            instance: 0,
            kind: ExportKind::Func,
            name: "run",
        });
        component.section(&aliases);
        let mut types = ComponentTypeSection::new();
        types
            .function()
            .params([] as [(&str, ComponentValType); 0])
            .result(Some(PrimitiveValType::U32.into()));
        component.section(&types);
        let mut canonical = CanonicalFunctionSection::new();
        canonical.lift(0, 0, []);
        component.section(&canonical);
        let mut exports = ComponentExportSection::new();
        exports.export("run", ComponentExportKind::Func, 0, None);
        component.section(&exports);
        component.finish()
    }

    fn gc_type_module() -> Vec<u8> {
        let mut module = wasm_encoder::Module::new();
        let mut types = wasm_encoder::TypeSection::new();
        types.ty().struct_([]);
        module.section(&types);
        module.finish()
    }

    #[test]
    fn ordinary_profile_preserves_typed_function_references_without_enabling_gc() {
        let bytes = typed_function_component();
        let mut config = Config::new();
        let ordinary = WasmtimeConfig::default();
        ordinary.apply_engine(&mut config).unwrap();
        let engine = Engine::new(&config).unwrap();
        let component = component::Component::new(&engine, &bytes)
            .expect("the ordinary pre-Java profile accepted internal ref.func and call_ref");
        let linker = component::Linker::<()>::new(&engine);
        let mut store = Store::new(&engine, ());
        store.set_fuel(10_000).unwrap();
        store.set_epoch_deadline(1);
        let instance = linker.instantiate(&mut store, &component).unwrap();
        let run = instance
            .get_typed_func::<(), (u32,)>(&mut store, "run")
            .unwrap();
        assert_eq!(run.call(&mut store, ()).unwrap(), (42,));
        assert!(Module::new(&engine, gc_type_module()).is_err());

        let java = WasmtimeConfig {
            java_guest: true,
            fuel_async_yield_interval: Some(10_000),
            ..WasmtimeConfig::default()
        };
        let mut config = Config::new();
        java.apply_engine(&mut config).unwrap();
        let java_engine = Engine::new(&config).unwrap();
        assert!(component::Component::new(&java_engine, &bytes).is_err());
        assert!(Module::new(&java_engine, gc_type_module()).is_err());
    }

    #[test]
    fn java_exception_profile_is_explicit_fixed_and_cache_distinct() {
        let mut policy = WasmtimeConfig {
            fuel_async_yield_interval: Some(10_000),
            ..WasmtimeConfig::default()
        };
        let before = policy.clone();
        policy.install_java_guest();
        policy.validate().unwrap();
        assert_eq!(policy.maximum_memory_bytes, before.maximum_memory_bytes);
        assert_eq!(policy.maximum_fuel, before.maximum_fuel);
        assert_eq!(policy.cache_limits(), before.cache_limits());
        assert_ne!(
            policy.configuration_digest(DispatchMode::Generic),
            before.configuration_digest(DispatchMode::Generic)
        );
        for (profile, function_references, exceptions) in
            [(&before, "true", "false"), (&policy, "false", "true")]
        {
            let fields = profile.profile(DispatchMode::Generic).configuration;
            assert_eq!(fields["wasm-function-references"], function_references);
            assert_eq!(fields["wasm-gc"], "false");
            assert_eq!(fields["wasm-exceptions"], exceptions);
        }
        let mut config = Config::new();
        policy.apply_engine(&mut config).unwrap();
        let engine = Engine::new(&config).unwrap();
        assert_eq!(
            engine.get_gc_heap_reservation(),
            JAVA_EXCEPTION_HEAP_BYTES as u64
        );
        assert_eq!(
            engine.get_gc_heap_initial_size(),
            JAVA_EXCEPTION_HEAP_INITIAL_BYTES
        );
        assert_eq!(engine.get_gc_heap_reservation_for_growth(), 0);
        assert!(!engine.get_gc_heap_may_move());
        assert!(engine.get_consume_fuel() && engine.get_epoch_interruption());
        for mutate in [
            (|c: &mut WasmtimeConfig| c.instance_allocator = InstanceAllocator::Pooling)
                as fn(&mut WasmtimeConfig),
            |c| c.angular_renderer = true,
            |c| c.maximum_memory_bytes = JAVA_EXCEPTION_HEAP_BYTES as u64,
            |c| c.fuel_async_yield_interval = None,
        ] {
            let mut wrong = policy.clone();
            mutate(&mut wrong);
            assert!(wrong.validate().is_err());
        }
    }
}
