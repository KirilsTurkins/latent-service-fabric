//! Implements a registry of modules for a store.

use super::native_registry::{RegistryIndices, RegistryMap};
use crate::code::{EngineCode, EngineCodePC, ModuleWithCode, StoreCode, StoreCodePC};
#[cfg(feature = "component-model")]
use crate::component::Component;
use crate::runtime::native_memory::Memory;
use crate::runtime::vm::VMWasmCallFunction;
use crate::sync::{OnceLock, RwLock};
use crate::vm::CompiledModuleId;
use crate::{Engine, FrameInfo, Module, code_memory::CodeMemory, prelude::*};
use alloc::sync::Arc;
#[cfg(not(feature = "debug"))]
use core::marker::PhantomData;
use core::ops::Range;
use core::ptr::NonNull;
use wasmtime_environ::{
    CompiledFunctionsTable, FuncKey, StaticModuleIndex, VMSharedTypeIndex,
    collections::btree_map::Entry,
};

/// Used for registering modules with a store.
///
/// There are two basic purposes that this registry serves:
///
/// - It keeps all modules and their metadata alive as long as the
///   store exists.
/// - It owns the [`StoreCode`], i.e. possibly-private-copy of machine
///   code, for all modules that execute in this store.
///
/// The registry allows for translation of EngineCode to StoreCode,
/// deduplicating by the start address of the EngineCode; and allows
/// for looking up modules by "registered module ID", and looking up
/// StoreCode and Modules by PC.
///
/// Note that multiple modules may be backed by a single
/// `StoreCode`. This is specifically the case for components in
/// general. When a component is first instantiated, the component
/// itself is registered (which loads the StoreCode into the
/// registry), then each individual module within that component is
/// registered and added to the data structures.
///
/// A brief overview of the kinds of compiled object and their
/// relationships:
///
/// - `Module` is a Wasm module. It owns a `CompiledModule`.
/// - `CompiledModule` contains metadata about the module (e.g., a map
///   from Wasm function indices to locations in the machine code),
///   and also owns an `EngineCode`.
/// - `EngineCode` holds an `Arc` to a `CodeMemory` with the canonical
///   copy of machine code, as well as some lower-level metadata
///   (signatures and types). It is instantiated by this registry into
///   `StoreCode`.
/// - `StoreCode` owns either another `Arc` to the same `CodeMemory`
///   as `EngineCode`, or if guest debugging is enabled and causes us
///   to clone private copies of code for patching per store, owns its
///   own private `CodeMemory` at a different address.
/// - Instances hold a `RegisteredModuleId` to be able to look up their modules.
#[derive(Default)]
pub struct ModuleRegistry {
    /// StoreCode and Modules associated with it.
    ///
    /// Keyed by the start address of the `StoreCode`. We maintain the
    /// invariant of no overlaps on insertion. We use a range query to
    /// find the StoreCode for a given PC: take the range `0..=pc`,
    /// then take the last element of the range. That picks the
    /// highest start address <= the query, and we can check whether
    /// it contains the address.
    loaded_code: RegistryMap<StoreCodePC, LoadedCode>,

    /// Map from EngineCodePC start to StoreCodePC start. We use this
    /// to memoize the store-code creation process: each EngineCode is
    /// instantiated to a StoreCode only once per store.
    store_code: RegistryMap<EngineCodePC, StoreCodePC>,

    /// Modules instantiated in this registry.
    ///
    /// Every module is placed in this map, but not every module will
    /// be in a LoadedCode entry, because the module may have no text.
    modules: RegistryMap<RegisteredModuleId, Module>,

    // Retain the factory after every registry buffer and its affine owner.
    memory: Memory,
}

struct LoadedCode {
    /// The StoreCode in this range.
    code: StoreCode,

    /// The index of compiled functions in `code`.
    ///
    /// This index is used to map from program counters back to a `FuncKey`.
    /// Primarily used in [`ModuleRegistry::lookup_frame_info`] at this time
    /// below.
    index: Arc<CompiledFunctionsTable>,

    /// A mapping from the [`StaticModuleIndex`] values returned by the `index`
    /// field above to a module within this registry.
    ///
    /// This is lazily populated as modules are registered and instantiated from
    /// a component.
    modules: RegistryIndices,
}

/// An identifier of a module that has previously been inserted into a
/// `ModuleRegistry`.
///
/// This is just a newtype around `CompiledModuleId`, which is unique
/// within the Engine.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct RegisteredModuleId(CompiledModuleId);

fn assert_no_overlap(
    loaded_code: &RegistryMap<StoreCodePC, LoadedCode>,
    range: Range<StoreCodePC>,
) {
    if let Some((start, _)) = loaded_code.range(range.start..).next() {
        assert!(start >= range.end);
    }
    if let Some((_, code)) = loaded_code.range(..range.end).next_back() {
        assert!(code.code.text_range().end <= range.start);
    }
}

#[cfg(feature = "debug")]
pub struct RegisterBreakpointState<'a>(pub(crate) &'a crate::runtime::debug::BreakpointState);
#[cfg(not(feature = "debug"))]
pub struct RegisterBreakpointState<'a>(pub(crate) PhantomData<&'a ()>);

impl<'a> RegisterBreakpointState<'a> {
    #[cfg(feature = "debug")]
    fn update(&self, code: &mut StoreCode, module: &Module) -> Result<()> {
        self.0.patch_new_module(code, module)
    }
    #[cfg(not(feature = "debug"))]
    fn update(&self, _code: &mut StoreCode, _module: &Module) -> Result<()> {
        Ok(())
    }
}

enum ModuleOrComponent<'a> {
    Module(&'a Module),
    #[cfg(feature = "component-model")]
    Component(&'a Component),
}

impl<'a> ModuleOrComponent<'a> {
    fn engine(&self) -> &'a Engine {
        match self {
            ModuleOrComponent::Module(module) => module.engine(),
            #[cfg(feature = "component-model")]
            ModuleOrComponent::Component(component) => component.engine(),
        }
    }
}

impl ModuleRegistry {
    pub(crate) fn new(memory: Memory) -> Result<Self> {
        Ok(Self {
            loaded_code: RegistryMap::new(memory.clone())?,
            store_code: RegistryMap::new(memory.clone())?,
            modules: RegistryMap::new(memory.clone())?,
            memory,
        })
    }

    /// Get a previously-registered module by id.
    pub fn module_by_id(&self, id: RegisteredModuleId) -> Option<&Module> {
        self.modules.get(id)
    }

    /// Get a module by CompiledModuleId, if present.
    pub fn module_by_compiled_id(&self, id: CompiledModuleId) -> Option<&Module> {
        self.modules.get(RegisteredModuleId(id))
    }

    /// Looks up `pc`, an absolute program counter address, to see if it
    /// corresponds to any loaded code within this [`ModuleRegistry`].
    ///
    /// Returns `None` if nothing is found, and otherwise returns the
    /// corresponding [`LoadedCode`] as well as a relative pc from the start of
    /// the code's text section if found.
    fn loaded_code_by_pc(&self, pc: usize) -> Option<(&LoadedCode, usize)> {
        let (_, code) = self
            .loaded_code
            .range(..=StoreCodePC::from_raw(pc))
            .next_back()?;
        let offset = StoreCodePC::offset_of(code.code.text_range(), pc)?;
        Some((code, offset))
    }

    /// Consults this [`ModuleRegistry`] to see if `pc` corrseponds to any
    /// previously-registered block of code.
    ///
    /// Upon success returns the [`StoreCode`] as well as a relative pc from the
    /// start of the text section.
    pub fn store_code_by_pc(&self, pc: usize) -> Option<(&StoreCode, usize)> {
        let (code, pc) = self.loaded_code_by_pc(pc)?;
        Some((&code.code, pc))
    }

    /// Fetches the `StoreCode` for a given `EngineCode`.
    pub fn store_code(&self, engine_code: &EngineCode) -> Option<&StoreCode> {
        let store_code_pc = self.store_code_base(engine_code)?;
        let (_, code) = self.loaded_code.range(store_code_pc..).next()?;
        Some(&code.code)
    }

    /// Fetches the base `StoreCodePC` for a given `EngineCode`.
    pub fn store_code_base(&self, engine_code: &EngineCode) -> Option<StoreCodePC> {
        self.store_code.get(engine_code.text_range().start).cloned()
    }

    /// Fetches the base `StoreCodePC` for a given `EngineCode` with
    /// `Module`, registering the module if not already registered.
    pub fn store_code_base_or_register(
        &mut self,
        module: &Module,
        breakpoint_state: RegisterBreakpointState,
    ) -> Result<StoreCodePC> {
        let key = module.engine_code().text_range().start;
        if !self.store_code.contains_key(key) {
            let engine = module.engine().clone();
            self.register_module(module, &engine, breakpoint_state)?;
        }
        Ok(*self.store_code.get(key).unwrap())
    }

    /// Fetches a mutable `StoreCode` for a given base `StoreCodePC`.
    pub fn store_code_mut(&mut self, store_code_base: StoreCodePC) -> Option<&mut StoreCode> {
        let (_, code) = self.loaded_code.range_mut(store_code_base..).next()?;
        assert_eq!(code.code.text_range().start, store_code_base);
        Some(&mut code.code)
    }

    /// Gets an iterator over all modules in the registry.
    #[cfg(any(feature = "coredump", feature = "debug", feature = "gc"))]
    pub fn all_modules(&self) -> impl Iterator<Item = (RegisteredModuleId, &'_ Module)> + '_ {
        self.modules.iter()
    }

    /// Registers a new module with the registry.
    ///
    /// Returns an error if `module` was not compiled by `engine`.
    pub fn register_module(
        &mut self,
        module: &Module,
        engine: &Engine,
        breakpoint_state: RegisterBreakpointState,
    ) -> Result<RegisteredModuleId> {
        self.register(ModuleOrComponent::Module(module), engine, breakpoint_state)
            .map(|id| id.unwrap())
    }

    /// Registers a new component with the registry.
    ///
    /// Returns an error if `component` was not compiled by `engine`.
    #[cfg(feature = "component-model")]
    pub fn register_component(
        &mut self,
        component: &Component,
        engine: &Engine,
        breakpoint_state: RegisterBreakpointState,
    ) -> Result<()> {
        self.register(
            ModuleOrComponent::Component(component),
            engine,
            breakpoint_state,
        )?;
        Ok(())
    }

    /// Registers a new module with the registry.
    ///
    /// Returns an error if `module_or_component` was not compiled by `engine`.
    /// All code and metadata enters a store through here, so callers
    /// registering on a store's behalf pass that store's engine to keep foreign
    /// code out of it.
    fn register(
        &mut self,
        module_or_component: ModuleOrComponent<'_>,
        engine: &Engine,
        breakpoint_state: RegisterBreakpointState,
    ) -> Result<Option<RegisteredModuleId>> {
        // Nothing below here may run for a foreign module or component: the
        // type indices it carries mean something else entirely in this
        // engine.
        ensure!(
            Engine::same(engine, module_or_component.engine()),
            "cross-`Engine` usage is not supported"
        );
        if self.memory.is_some() {
            return self.register_accounted(module_or_component, engine, breakpoint_state);
        }
        let compiled_id = match module_or_component {
            ModuleOrComponent::Module(module) => module.id(),
            #[cfg(feature = "component-model")]
            ModuleOrComponent::Component(component) => component.id(),
        };
        let code = match module_or_component {
            ModuleOrComponent::Module(module) => module.engine_code(),
            #[cfg(feature = "component-model")]
            ModuleOrComponent::Component(component) => component.engine_code(),
        };
        // Register the module, if any.
        let id = match module_or_component {
            ModuleOrComponent::Module(module) => {
                let id = RegisteredModuleId(compiled_id);
                self.modules
                    .legacy_entry(id)
                    .or_insert_with(|| module.clone())?;
                Some(id)
            }
            #[cfg(feature = "component-model")]
            ModuleOrComponent::Component(_) => None,
        };

        // Create a StoreCode if one does not already exist.
        let store_code_pc = match self.store_code.legacy_entry(code.text_range().start) {
            Entry::Vacant(v) => {
                let store_code = StoreCode::new(engine, code)?;
                let store_code_pc = store_code.text_range().start;
                assert_no_overlap(&self.loaded_code, store_code.text_range());
                let index = match module_or_component {
                    ModuleOrComponent::Module(module) => module.index(),
                    #[cfg(feature = "component-model")]
                    ModuleOrComponent::Component(component) => component.index(),
                };
                self.loaded_code.insert_prepared(
                    store_code_pc,
                    LoadedCode {
                        code: store_code,
                        index: index.clone(),
                        modules: Default::default(),
                    },
                )?;
                *v.insert(store_code_pc)?
            }
            Entry::Occupied(o) => *o.get(),
        };

        // Add this module to the LoadedCode if not present.
        if let (ModuleOrComponent::Module(module), Some(id)) = (module_or_component, id) {
            let loaded_code = self
                .loaded_code
                .get_mut(store_code_pc)
                .expect("loaded_code must have entry for StoreCodePC");
            loaded_code
                .modules
                .insert_prepared(module.env_module().module_index, Some(id))?;
            breakpoint_state.update(&mut loaded_code.code, module)?;
        }

        Ok(id)
    }

    /// Accounted registration stages every replacement before publishing any
    /// module/code/index edge. A later admission refusal drops only those
    /// empty replacements, retaining all previous registry values and owners.
    /// The caller has already rejected a foreign Engine before reaching here.
    fn register_accounted(
        &mut self,
        module_or_component: ModuleOrComponent<'_>,
        engine: &Engine,
        breakpoint_state: RegisterBreakpointState,
    ) -> Result<Option<RegisteredModuleId>> {
        let (id, code, index) = match module_or_component {
            ModuleOrComponent::Module(module) => (
                Some(RegisteredModuleId(module.id())),
                module.engine_code(),
                module.index(),
            ),
            #[cfg(feature = "component-model")]
            ModuleOrComponent::Component(component) => {
                (None, component.engine_code(), component.index())
            }
        };
        let code_key = code.text_range().start;
        let existing = self.store_code.get(code_key).copied();
        let mut pending_code = if existing.is_none() {
            let store_code = StoreCode::new(engine, code)?;
            assert_no_overlap(&self.loaded_code, store_code.text_range());
            Some(LoadedCode {
                code: store_code,
                index: index.clone(),
                modules: RegistryIndices::new(self.memory.clone())?,
            })
        } else {
            None
        };
        let pc = existing.unwrap_or_else(|| pending_code.as_ref().unwrap().code.text_range().start);
        let module_capacity = match id {
            Some(id) => self.modules.prepare_insert(id)?,
            None => None,
        };
        let loaded_capacity = if pending_code.is_some() {
            self.loaded_code.prepare_insert(pc)?
        } else {
            None
        };
        let code_capacity = if pending_code.is_some() {
            self.store_code.prepare_insert(code_key)?
        } else {
            None
        };
        let secondary_capacity = match module_or_component {
            ModuleOrComponent::Module(module) => {
                let loaded = pending_code.as_ref().unwrap_or_else(|| {
                    self.loaded_code
                        .get(pc)
                        .expect("registered code must have a loaded entry")
                });
                loaded
                    .modules
                    .prepare_index(module.env_module().module_index)?
            }
            #[cfg(feature = "component-model")]
            ModuleOrComponent::Component(_) => None,
        };

        // All admission has finished. The accounted map insertions below use
        // only this staged capacity; there is no allocating Entry escape.
        self.modules.commit_capacity(module_capacity);
        self.loaded_code.commit_capacity(loaded_capacity);
        self.store_code.commit_capacity(code_capacity);
        if let Some(loaded) = pending_code.as_mut() {
            loaded.modules.commit_capacity(secondary_capacity);
        } else {
            self.loaded_code
                .get_mut(pc)
                .unwrap()
                .modules
                .commit_capacity(secondary_capacity);
        }
        if let (ModuleOrComponent::Module(module), Some(id)) = (&module_or_component, id) {
            if !self.modules.contains_key(id) {
                self.modules.insert_prepared(id, (*module).clone())?;
            }
        }
        if let Some(loaded) = pending_code {
            self.loaded_code.insert_prepared(pc, loaded)?;
            self.store_code.insert_prepared(code_key, pc)?;
        }
        if let (ModuleOrComponent::Module(module), Some(id)) = (module_or_component, id) {
            let loaded = self.loaded_code.get_mut(pc).unwrap();
            loaded
                .modules
                .insert_prepared(module.env_module().module_index, Some(id))?;
            // Retain the original breakpoint update and its failure semantics
            // after every complete registry edge has been installed.
            breakpoint_state.update(&mut loaded.code, module)?;
        }
        Ok(id)
    }

    // Borrowed numeric lookup: no FrameInfo, name, symbol, Module clone or Vec.
    // The Copy module key is private scratch for at-most-eight local ordinals.
    #[cfg(feature = "gc")]
    pub(crate) fn lookup_numeric_frame(
        &self,
        pc: usize,
    ) -> Option<(RegisteredModuleId, u32, Option<u32>, Option<u32>)> {
        let (code, text_offset) = self.loaded_code_by_pc(pc)?;
        let key = code
            .index
            .func_by_text_offset(u32::try_from(text_offset).ok()?)?;
        let FuncKey::DefinedWasmFunction(module_index, defined) = key else {
            return None;
        };
        let id = (*code.modules.get(module_index)?)?;
        let module = self.modules.get(id)?;
        let compiled = module.compiled_module();
        let function = compiled.module().func_index(defined).as_u32();
        let start = compiled.func_start_srcloc(key).file_offset();
        let instruction =
            wasmtime_environ::lookup_file_pos(module.engine_code().address_map_data(), text_offset)
                .and_then(|position| position.file_offset());
        let function_offset = instruction
            .zip(start)
            .and_then(|(instruction, start)| instruction.checked_sub(start));
        Some((id, function, instruction, function_offset))
    }

    /// Fetches frame information about a program counter in a backtrace.
    ///
    /// Returns an object if this `pc` is known to some previously registered
    /// module, or returns `None` if no information can be found. The first
    /// boolean returned indicates whether the original module has unparsed
    /// debug information due to the compiler's configuration. The second
    /// boolean indicates whether the engine used to compile this module is
    /// using environment variables to control debuginfo parsing.
    pub(crate) fn lookup_frame_info<'a>(
        &'a self,
        pc: usize,
    ) -> Option<(FrameInfo, ModuleWithCode<'a>)> {
        let (code, text_offset) = self.loaded_code_by_pc(pc)?;
        let module_index = match code
            .index
            .func_by_text_offset(u32::try_from(text_offset).ok()?)?
        {
            FuncKey::DefinedWasmFunction(module, _) => module,
            _ => return None,
        };
        let module_id = (*code.modules.get(module_index)?)?;
        let module = self
            .modules
            .get(module_id)
            .expect("referenced module ID not found");
        let info = FrameInfo::new(module.clone(), text_offset)?;
        let module_with_code = ModuleWithCode::from_raw(module, &code.code);
        Some((info, module_with_code))
    }

    pub fn wasm_to_array_trampoline(
        &self,
        sig: VMSharedTypeIndex,
    ) -> Option<NonNull<VMWasmCallFunction>> {
        // TODO: We are doing a linear search over each module. This is fine for
        // now because we typically have very few modules per store (almost
        // always one, in fact). If this linear search ever becomes a
        // bottleneck, we could avoid it by incrementally and lazily building a
        // `VMSharedSignatureIndex` to `SignatureIndex` map.
        //
        // See also the comment in `ModuleInner::wasm_to_native_trampoline`.
        for module in self.modules.values() {
            if let Some(trampoline) = module.wasm_to_array_trampoline(sig) {
                return Some(trampoline);
            }
        }
        None
    }
}

// This is the global code registry that stores information for all loaded code
// objects that are currently in use by any `Store` in the current process.
//
// The purpose of this map is to be called from signal handlers to determine
// whether a program counter is a wasm trap or not. Specifically macOS has
// no contextual information about the thread available, hence the necessity
// for global state rather than using thread local state.
//
// This is similar to `ModuleRegistry` except that it has less information and
// supports removal. Any time anything is registered with a `ModuleRegistry`
// it is also automatically registered with the singleton global module
// registry. When a `ModuleRegistry` is destroyed then all of its entries
// are removed from the global registry.
fn global_code() -> &'static RwLock<GlobalRegistry> {
    static GLOBAL_CODE: OnceLock<RwLock<GlobalRegistry>> = OnceLock::new();
    GLOBAL_CODE.get_or_init(Default::default)
}

type GlobalRegistry = TryBTreeMap<usize, (usize, Arc<CodeMemory>)>;

/// Find which registered region of code contains the given program counter, and
/// what offset that PC is within that module's code.
pub fn lookup_code(pc: usize) -> Option<(Arc<CodeMemory>, usize)> {
    let all_modules = global_code().read();
    let (_end, (start, module)) = all_modules.range(pc..).next()?;
    let text_offset = pc.checked_sub(*start)?;
    Some((module.clone(), text_offset))
}

/// Registers a new region of code.
///
/// Must not have been previously registered and must be `unregister`'d to
/// prevent leaking memory.
///
/// This is required to enable traps to work correctly since the signal handler
/// will lookup in the `GLOBAL_CODE` list to determine which a particular pc
/// is a trap or not.
pub fn register_code(image: &Arc<CodeMemory>, address: Range<usize>) -> Result<(), OutOfMemory> {
    if address.is_empty() {
        return Ok(());
    }
    let start = address.start;
    let end = address.end - 1;
    let prev = global_code().write().insert(end, (start, image.clone()))?;
    assert!(prev.is_none());
    Ok(())
}

/// Unregisters a code mmap from the global map.
///
/// Must have been previously registered with `register`.
pub fn unregister_code(address: Range<usize>) {
    if address.is_empty() {
        return;
    }
    let end = address.end - 1;
    let code = global_code().write().remove(end);
    assert!(code.is_some());
}

#[test]
#[cfg_attr(miri, ignore)]
fn test_frame_info() -> Result<(), crate::Error> {
    use crate::*;

    let mut store = Store::<()>::default();
    let module = Module::new(
        store.engine(),
        r#"
            (module
                (func (export "add") (param $x i32) (param $y i32) (result i32) (i32.add (local.get $x) (local.get $y)))
                (func (export "sub") (param $x i32) (param $y i32) (result i32) (i32.sub (local.get $x) (local.get $y)))
                (func (export "mul") (param $x i32) (param $y i32) (result i32) (i32.mul (local.get $x) (local.get $y)))
                (func (export "div_s") (param $x i32) (param $y i32) (result i32) (i32.div_s (local.get $x) (local.get $y)))
                (func (export "div_u") (param $x i32) (param $y i32) (result i32) (i32.div_u (local.get $x) (local.get $y)))
                (func (export "rem_s") (param $x i32) (param $y i32) (result i32) (i32.rem_s (local.get $x) (local.get $y)))
                (func (export "rem_u") (param $x i32) (param $y i32) (result i32) (i32.rem_u (local.get $x) (local.get $y)))
            )
         "#,
    )?;
    // Create an instance to ensure the frame information is registered.
    Instance::new(&mut store, &module, &[])?;

    // Look for frame info for each function. Assume that StoreCode
    // does not actually clone in the default configuration.
    for (i, range) in module.compiled_module().finished_function_ranges() {
        let base = module.engine_code().text_range().start.raw();
        let start = base + range.start;
        let end = base + range.end;
        for pc in start..end {
            let (frame, _) = store
                .as_context()
                .0
                .modules()
                .lookup_frame_info(pc)
                .unwrap();
            assert!(
                frame.func_index() == i.as_u32(),
                "lookup of {:#x} returned {}, expected {}",
                pc,
                frame.func_index(),
                i.as_u32()
            );
        }
    }
    Ok(())
}
