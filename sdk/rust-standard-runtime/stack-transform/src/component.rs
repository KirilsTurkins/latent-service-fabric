//! Authenticate the complete finite main/thunk/fixup routing emitted by the
//! maintained encoder. No custom section, application marker or claimed hash
//! enables threading. This source verifier does not change the host feature.
use super::*;
use std::collections::BTreeMap;
use wasmparser::{CanonicalFunction, CanonicalOption, ComponentAlias, ComponentExternalKind,
    ComponentTypeRef, ElementItems, ElementKind, Instance};

const NATIVE: &str = "latent:runtime-native/threads@0.1.0";
const NEW: &str = "[thread-new-indirect-v0]";
const MAX_SLOTS: usize = 256;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ComponentRoutingReceipt {
    pub component_digest: [u8; 32],
    pub main_core_digest: [u8; 32],
    pub main_module: u32,
    pub shim_module: u32,
    pub fixup_module: u32,
    pub raw_creation_slot: u32,
    pub native_admission_slot: u32,
    pub component_routing_authenticated: bool,
    pub canonical_creation_enabled: bool,
    pub standard_runtime_qualified: bool,
}

#[derive(Clone, Debug, PartialEq, Eq)]
struct Signature { params: Vec<ValType>, results: Vec<ValType> }
fn signature(ty: wasmparser::FuncType) -> Result<Signature, &'static str> {
    fn values(types: &[wasmparser::ValType]) -> Result<Vec<ValType>, &'static str> {
        types.iter().map(|ty| Ok(match ty {
            wasmparser::ValType::I32 => ValType::I32,
            wasmparser::ValType::I64 => ValType::I64,
            wasmparser::ValType::F32 => ValType::F32,
            wasmparser::ValType::F64 => ValType::F64,
            _ => return Err("rust-component-nonnumeric-shim-abi"),
        })).collect()
    }
    if ty.params().len() > 64 || ty.results().len() > 16 { return Err("rust-component-shim-flat-limit"); }
    Ok(Signature { params: values(ty.params())?, results: values(ty.results())? })
}

#[derive(Clone, Debug)]
struct Import { module: String, name: String, function_type: u32 }
struct Core<'a> {
    bytes: &'a [u8], types: Vec<Signature>, imports: Vec<Import>, functions: Vec<u32>,
    exports: BTreeMap<String, (ExternalKind, u32)>, bodies: Vec<wasmparser::FunctionBody<'a>>,
    local_table: Option<wasmparser::TableType>, imported_table: Option<wasmparser::TableType>,
    element: Option<Vec<u32>>, unsupported_helper_sections: bool,
    nonfunction_imports: bool,
}
fn finite_table(ty: wasmparser::TableType, count: usize) -> bool {
    ty.element_type == wasmparser::RefType::FUNCREF && !ty.table64 && !ty.shared
        && ty.initial == count as u64 && ty.maximum == Some(count as u64)
}
fn core(bytes: &[u8]) -> Result<Core<'_>, &'static str> {
    let mut value = Core { bytes, types: vec![], imports: vec![], functions: vec![], exports: BTreeMap::new(),
        bodies: vec![], local_table: None, imported_table: None, element: None,
        unsupported_helper_sections: false, nonfunction_imports: false };
    for payload in Parser::new(0).parse_all(bytes) {
        match payload.map_err(|_| "rust-component-core-parse")? {
            Payload::Version { encoding: Encoding::Module, .. } | Payload::End(_) | Payload::CustomSection(_) => {},
            Payload::TypeSection(reader) => for ty in reader.into_iter_err_on_gc_types() {
                value.types.push(signature(ty.map_err(|_| "rust-component-core-types")?)?);
            },
            Payload::ImportSection(reader) => for import in reader.into_imports() {
                let import = import.map_err(|_| "rust-component-core-import")?;
                match import.ty {
                    TypeRef::Func(function_type) | TypeRef::FuncExact(function_type) => value.imports.push(Import {
                        module: import.module.into(), name: import.name.into(), function_type }),
                    TypeRef::Table(ty) if import.module.is_empty() && import.name == "$imports"
                        && value.imported_table.replace(ty).is_none() => value.nonfunction_imports = true,
                    _ => { value.nonfunction_imports = true; value.unsupported_helper_sections = true; },
                }
            },
            Payload::FunctionSection(reader) => for ty in reader {
                value.functions.push(ty.map_err(|_| "rust-component-core-function")?);
            },
            Payload::ExportSection(reader) => for export in reader {
                let export = export.map_err(|_| "rust-component-core-export")?;
                if value.exports.insert(export.name.into(), (export.kind, export.index)).is_some() {
                    return Err("rust-component-duplicate-core-export");
                }
            },
            Payload::TableSection(reader) => for table in reader {
                let table = table.map_err(|_| "rust-component-core-table")?;
                if value.local_table.replace(table.ty).is_some() { return Err("rust-component-helper-table-count"); }
                if !matches!(table.init, wasmparser::TableInit::RefNull) { value.unsupported_helper_sections = true; }
            },
            Payload::CodeSectionStart { .. } => {},
            Payload::CodeSectionEntry(body) => value.bodies.push(body),
            Payload::ElementSection(reader) => for element in reader {
                let element = element.map_err(|_| "rust-component-fixup-element")?;
                let ElementKind::Active { table_index, offset_expr } = element.kind else {
                    value.unsupported_helper_sections = true; continue;
                };
                let mut ops = offset_expr.get_operators_reader();
                if table_index.unwrap_or(0) != 0
                    || !matches!(ops.read().map_err(|_| "rust-component-element-offset")?, Operator::I32Const { value: 0 })
                    || !matches!(ops.read().map_err(|_| "rust-component-element-offset")?, Operator::End) || !ops.eof() {
                    value.unsupported_helper_sections = true;
                }
                let ElementItems::Functions(reader) = element.items else {
                    value.unsupported_helper_sections = true; continue;
                };
                let functions = reader.into_iter().collect::<Result<Vec<_>, _>>().map_err(|_| "rust-component-element-functions")?;
                if value.element.replace(functions).is_some() { return Err("rust-component-fixup-element-count"); }
            },
            _ => value.unsupported_helper_sections = true,
        }
    }
    Ok(value)
}

impl Core<'_> {
    fn shim(&self) -> Result<Vec<Signature>, &'static str> {
        let n = self.functions.len();
        if n == 0 || n > MAX_SLOTS || self.unsupported_helper_sections || !self.imports.is_empty()
            || self.imported_table.is_some() || !self.local_table.is_some_and(|ty| finite_table(ty, n))
            || self.element.is_some() || self.bodies.len() != n || self.exports.len() != n + 1
            || self.exports.get("$imports") != Some(&(ExternalKind::Table, 0)) {
            return Err("rust-component-private-shim-shape");
        }
        let mut signatures = Vec::new();
        for (slot, (&ty, body)) in self.functions.iter().zip(&self.bodies).enumerate() {
            if self.exports.get(&slot.to_string()) != Some(&(ExternalKind::Func, slot as u32)) {
                return Err("rust-component-private-shim-export");
            }
            let sig = self.types.get(ty as usize).ok_or("rust-component-private-shim-type")?;
            let mut expected = Function::new([]);
            for index in 0..sig.params.len() as u32 { expected.instruction(&Instruction::LocalGet(index)); }
            expected.instruction(&Instruction::I32Const(slot as i32))
                .instruction(&Instruction::CallIndirect { type_index: ty, table_index: 0 }).instruction(&Instruction::End);
            if body_bytes(self.bytes, body)? != expected.into_raw_body() {
                return Err("rust-component-private-shim-body");
            }
            signatures.push(sig.clone());
        }
        Ok(signatures)
    }
    fn fixup(&self, signatures: &[Signature]) -> Result<(), &'static str> {
        let n = signatures.len();
        if self.unsupported_helper_sections || self.local_table.is_some()
            || !self.imported_table.is_some_and(|ty| finite_table(ty, n))
            || !self.functions.is_empty() || !self.bodies.is_empty() || !self.exports.is_empty()
            || self.imports.len() != n || self.element.as_deref() != Some(&(0..n as u32).collect::<Vec<_>>()) {
            return Err("rust-component-private-fixup-shape");
        }
        for (slot, (import, sig)) in self.imports.iter().zip(signatures).enumerate() {
            if !import.module.is_empty() || import.name != slot.to_string()
                || self.types.get(import.function_type as usize) != Some(sig) {
                return Err("rust-component-private-fixup-signature");
            }
        }
        Ok(())
    }
}
fn body_bytes<'a>(input: &'a [u8], body: &wasmparser::FunctionBody<'_>) -> Result<&'a [u8], &'static str> {
    let range = body.range();
    let start = usize::try_from(range.start).map_err(|_| "rust-component-body-range")?;
    let end = usize::try_from(range.end).map_err(|_| "rust-component-body-range")?;
    input.get(start..end).ok_or("rust-component-body-range")
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Value { Raw, Native, Shim(u32), MainFunc(u32), ShimTable, MainTable(u32), MainMemory(u32), Other }
#[derive(Clone)]
struct CoreInstance { exports: BTreeMap<String, Value>, kind: u8, arguments: BTreeMap<String, u32> }
impl CoreInstance { fn value(&self, name: &str) -> Result<Value, &'static str> {
    self.exports.get(name).copied().ok_or("rust-component-core-alias-export")
} }
struct Graph<'a> {
    cores: Vec<Core<'a>>, main: usize, shim: usize, fixup: usize,
    admission: admission::Admission, signatures: Vec<Signature>,
    funcs: Vec<Value>, tables: Vec<Value>, memories: Vec<Value>, instances: Vec<CoreInstance>,
    component_instances: Vec<bool>, component_funcs: Vec<bool>, native_imports: usize,
    main_instances: Vec<usize>, shim_instances: usize, fixup_instances: Vec<usize>,
    main_imports: Vec<Value>, raw_table: Option<Value>, native_memory: Option<Value>,
    denied_uses: Vec<Value>, raw_alias: bool,
}

fn forbidden_creation(function: &CanonicalFunction) -> bool {
    matches!(function, CanonicalFunction::ThreadSpawnRef { .. } | CanonicalFunction::ThreadSpawnIndirect { .. })
}

/// Extract only root core modules. Nested WIT export wrappers cannot import a
/// dynamic module/component or contain another executable core module/creator.
fn modules(input: &[u8]) -> Result<Vec<&[u8]>, &'static str> {
    if input.len() > MAX_BYTES { return Err("rust-component-byte-limit"); }
    Validator::new_with_features(wasmparser::WasmFeatures::all()).validate_all(input)
        .map_err(|_| "rust-component-invalid")?;
    let mut stack = Vec::new(); let mut modules = Vec::new();
    for payload in Parser::new(0).parse_all(input) {
        match payload.map_err(|_| "rust-component-parse")? {
            Payload::Version { encoding, .. } => {
                if stack.is_empty() && encoding != Encoding::Component { return Err("rust-component-required"); }
                stack.push(encoding);
            },
            Payload::End(_) => { stack.pop(); },
            Payload::ModuleSection { unchecked_range, .. } => {
                if stack.len() != 1 || modules.len() == 3 { return Err("rust-component-finite-three-module-profile"); }
                let start = usize::try_from(unchecked_range.start).map_err(|_| "rust-component-module-range")?;
                let end = usize::try_from(unchecked_range.end).map_err(|_| "rust-component-module-range")?;
                modules.push(input.get(start..end).ok_or("rust-component-module-range")?);
            },
            Payload::ComponentCanonicalSection(reader) => for function in reader {
                let function = function.map_err(|_| "rust-component-canonical")?;
                if forbidden_creation(&function) { return Err("rust-component-parallel-spawn-denied"); }
                if stack.len() != 1 && matches!(function, CanonicalFunction::ThreadNewIndirect { .. }) {
                    return Err("rust-component-nested-creation-denied");
                }
            },
            Payload::ComponentImportSection(reader) => for import in reader {
                if matches!(import.map_err(|_| "rust-component-import")?.ty,
                    ComponentTypeRef::Module(_) | ComponentTypeRef::Component(_)) {
                    return Err("rust-component-dynamic-code-import-denied");
                }
            },
            Payload::ComponentStartSection { .. } => return Err("rust-component-start-before-owned-root-denied"),
            Payload::ComponentExportSection(reader) => for export in reader {
                if export.map_err(|_| "rust-component-export")?.kind == ComponentExternalKind::Module {
                    return Err("rust-component-private-module-export-denied");
                }
            },
            Payload::ComponentAliasSection(reader) => for alias in reader {
                let alias = alias.map_err(|_| "rust-component-alias")?;
                if matches!(alias, ComponentAlias::InstanceExport {
                    kind: ComponentExternalKind::Module | ComponentExternalKind::Component, .. }) {
                    return Err("rust-component-dynamic-code-alias-denied");
                }
                if matches!(alias, ComponentAlias::Outer {
                    kind: wasmparser::ComponentOuterAliasKind::CoreModule, .. }) {
                    return Err("rust-component-private-module-outer-alias-denied");
                }
            },
            _ => {}
        }
    }
    if modules.len() != 3 { return Err("rust-component-finite-three-module-profile"); }
    Ok(modules)
}

impl<'a> Graph<'a> {
    fn new(input: &'a [u8]) -> Result<Self, &'static str> {
        let cores = modules(input)?.into_iter().map(core).collect::<Result<Vec<_>, _>>()?;
        let mains = cores.iter().enumerate().filter(|(_, core)| core.imports.iter()
            .any(|i| i.module == "$root" && i.name == NEW)).map(|(i, _)| i).collect::<Vec<_>>();
        if mains.len() != 1 { return Err("rust-component-main-creation-import"); }
        let main = mains[0];
        // In particular, a direct `with` argument must never give the main
        // module the private shim table. Table imports are outside this owned
        // Rust target even when function-import routing otherwise looks valid.
        if cores[main].nonfunction_imports {
            return Err("rust-component-main-nonfunction-import-denied");
        }
        if !cores[main].local_table.is_some_and(|table| {
            table.element_type == wasmparser::RefType::FUNCREF && !table.table64 && !table.shared
                && table.initial <= 65_536 && table.maximum.is_some_and(|maximum| maximum <= 65_536)
        }) || cores[main].exports.get("__indirect_function_table") != Some(&(ExternalKind::Table, 0)) {
            return Err("rust-component-main-finite-original-table");
        }
        let admission = admission::verify_linked_core(cores[main].bytes)?;
        let shim = (0..3).find(|&i| i != main && cores[i].exports.contains_key("$imports"))
            .ok_or("rust-component-private-shim-missing")?;
        let fixup = (0..3).find(|&i| i != main && i != shim).unwrap();
        let signatures = cores[shim].shim()?; cores[fixup].fixup(&signatures)?;
        Ok(Self { cores, main, shim, fixup, admission, signatures, funcs: vec![], tables: vec![],
            memories: vec![], instances: vec![], component_instances: vec![], component_funcs: vec![],
            native_imports: 0, main_instances: vec![], shim_instances: 0, fixup_instances: vec![],
            main_imports: vec![], raw_table: None, native_memory: None, denied_uses: vec![], raw_alias: false })
    }
    fn indexed(values: &[Value], index: u32) -> Result<Value, &'static str> {
        values.get(index as usize).copied().ok_or("rust-component-value-index")
    }
    fn alias(&mut self, alias: ComponentAlias<'_>) -> Result<(), &'static str> {
        match alias {
            ComponentAlias::CoreInstanceExport { kind, instance_index, name } => {
                let value = self.instances.get(instance_index as usize).ok_or("rust-component-instance-index")?.value(name)?;
                match kind {
                    ExternalKind::Func => { self.raw_alias |= value == Value::Raw; self.funcs.push(value); },
                    ExternalKind::Table => self.tables.push(value),
                    ExternalKind::Memory => self.memories.push(value),
                    _ => {},
                }
            },
            ComponentAlias::InstanceExport { kind, instance_index, name } => match kind {
                ComponentExternalKind::Func => self.component_funcs.push(
                    *self.component_instances.get(instance_index as usize).ok_or("rust-component-provider-instance-index")? && name == "start"),
                ComponentExternalKind::Instance => self.component_instances.push(false),
                _ => {},
            },
            _ => {},
        }
        Ok(())
    }
    fn canonical(&mut self, function: CanonicalFunction) -> Result<(), &'static str> {
        match function {
            CanonicalFunction::Lift { core_func_index, options, .. } => {
                self.denied_uses.push(Self::indexed(&self.funcs, core_func_index)?);
                self.options(&options)?; self.component_funcs.push(false);
            },
            CanonicalFunction::Lower { func_index, options } => {
                let native = *self.component_funcs.get(func_index as usize).ok_or("rust-component-lower-function-index")?;
                self.options(&options)?;
                if native {
                    if self.native_memory.is_some() || options.len() != 1 {
                        return Err("rust-component-native-lower-shape-or-duplicate");
                    }
                    let CanonicalOption::Memory(index) = options[0] else { return Err("rust-component-native-lower-memory"); };
                    self.native_memory = Some(Self::indexed(&self.memories, index)?);
                }
                self.funcs.push(if native { Value::Native } else { Value::Other });
            },
            CanonicalFunction::ThreadNewIndirect { table_index, .. } => {
                if self.raw_table.replace(Self::indexed(&self.tables, table_index)?).is_some() {
                    return Err("rust-component-duplicate-creation");
                }
                self.funcs.push(Value::Raw);
            },
            // All remaining canonical functions define exactly one core func.
            // Function options still participate in the raw/thunk use fence.
            other => {
                match &other {
                    CanonicalFunction::TaskReturn { options, .. }
                    | CanonicalFunction::StreamRead { options, .. }
                    | CanonicalFunction::StreamWrite { options, .. }
                    | CanonicalFunction::FutureRead { options, .. }
                    | CanonicalFunction::FutureWrite { options, .. }
                    | CanonicalFunction::ErrorContextNew { options }
                    | CanonicalFunction::ErrorContextDebugMessage { options } => self.options(options)?,
                    _ => {},
                }
                self.funcs.push(Value::Other);
            },
        }
        if self.funcs.len() > MAX_FUNCTIONS as usize { return Err("rust-component-function-limit"); }
        Ok(())
    }
    fn options(&mut self, options: &[CanonicalOption]) -> Result<(), &'static str> {
        for option in options {
            if let CanonicalOption::Realloc(index) | CanonicalOption::PostReturn(index) | CanonicalOption::Callback(index) = option {
                self.denied_uses.push(Self::indexed(&self.funcs, *index)?);
            }
        }
        Ok(())
    }
    fn instance(&mut self, instance: Instance<'_>) -> Result<(), &'static str> {
        let mut exports = BTreeMap::new(); let mut arguments = BTreeMap::new();
        let kind;
        match instance {
            Instance::FromExports(items) => {
                kind = 0;
                for item in items {
                    let value = match item.kind {
                        ExternalKind::Func => Self::indexed(&self.funcs, item.index)?,
                        ExternalKind::Table => Self::indexed(&self.tables, item.index)?,
                        ExternalKind::Memory => Self::indexed(&self.memories, item.index)?,
                        _ => Value::Other,
                    };
                    if exports.insert(item.name.into(), value).is_some() { return Err("rust-component-inline-export-duplicate"); }
                }
            },
            Instance::Instantiate { module_index, args } => {
                for arg in args {
                    if arg.index as usize >= self.instances.len() || arguments.insert(arg.name.into(), arg.index).is_some() {
                        return Err("rust-component-module-argument");
                    }
                }
                let module = module_index as usize;
                if module == self.shim {
                    kind = 1; self.shim_instances += 1;
                    if !arguments.is_empty() { return Err("rust-component-shim-arguments"); }
                    exports.insert("$imports".into(), Value::ShimTable);
                    for slot in 0..self.signatures.len() as u32 { exports.insert(slot.to_string(), Value::Shim(slot)); }
                } else if module == self.main {
                    kind = 2; self.main_instances.push(self.instances.len());
                    if self.main_instances.len() != 1 { return Err("rust-component-main-instantiated-twice"); }
                    for import in &self.cores[module].imports {
                        let instance = *arguments.get(&import.module).ok_or("rust-component-main-import-argument")? as usize;
                        self.main_imports.push(self.instances[instance].value(&import.name)?);
                    }
                    for (name, &(kind, index)) in &self.cores[module].exports {
                        exports.insert(name.clone(), match kind {
                            ExternalKind::Func => Value::MainFunc(index),
                            ExternalKind::Table => Value::MainTable(index),
                            ExternalKind::Memory => Value::MainMemory(index),
                            _ => Value::Other,
                        });
                    }
                } else if module == self.fixup {
                    kind = 3; self.fixup_instances.push(self.instances.len());
                } else { return Err("rust-component-unqualified-module-instantiation"); }
            },
        }
        if self.instances.len() > 4096 { return Err("rust-component-instance-limit"); }
        self.instances.push(CoreInstance { exports, kind, arguments }); Ok(())
    }
    fn scan(&mut self, input: &[u8]) -> Result<(), &'static str> {
        let mut depth = 0;
        for payload in Parser::new(0).parse_all(input) {
            let payload = payload.map_err(|_| "rust-component-graph-parse")?;
            match payload {
                Payload::Version { .. } => { depth += 1; continue; },
                Payload::End(_) => { depth -= 1; continue; },
                _ if depth != 1 => continue,
                _ => {},
            }
            match payload {
                Payload::ComponentImportSection(reader) => for import in reader {
                    let import = import.map_err(|_| "rust-component-graph-import")?;
                    match import.ty {
                        ComponentTypeRef::Instance(_) => {
                            let native = import.name.name == NATIVE;
                            self.native_imports += usize::from(native); self.component_instances.push(native);
                        },
                        ComponentTypeRef::Func(_) => self.component_funcs.push(false),
                        _ => {},
                    }
                },
                Payload::ComponentAliasSection(reader) => for alias in reader {
                    self.alias(alias.map_err(|_| "rust-component-graph-alias")?)?;
                },
                Payload::ComponentCanonicalSection(reader) => for function in reader {
                    self.canonical(function.map_err(|_| "rust-component-graph-canonical")?)?;
                },
                Payload::InstanceSection(reader) => for instance in reader {
                    self.instance(instance.map_err(|_| "rust-component-graph-instance")?)?;
                },
                Payload::ComponentInstanceSection(reader) => for instance in reader {
                    instance.map_err(|_| "rust-component-wrapper-instance")?;
                    self.component_instances.push(false);
                },
                Payload::ComponentExportSection(reader) => for export in reader {
                    let export = export.map_err(|_| "rust-component-graph-export")?;
                    match export.kind {
                        ComponentExternalKind::Func => self.component_funcs.push(*self.component_funcs.get(export.index as usize)
                            .ok_or("rust-component-export-function-index")?),
                        ComponentExternalKind::Instance => self.component_instances.push(false),
                        _ => {},
                    }
                },
                _ => {},
            }
        }
        Ok(())
    }
    fn finish(&self) -> Result<(u32, u32), &'static str> {
        if self.shim_instances != 1 || self.main_instances.len() != 1 || self.fixup_instances.len() != 1
            || self.native_imports != 1 || self.raw_alias
            || self.raw_table != Some(Value::MainTable(0)) || self.native_memory != Some(Value::MainMemory(0)) {
            return Err("rust-component-creator-provider-or-instance-fence");
        }
        let fixup = &self.instances[self.fixup_instances[0]];
        if fixup.arguments.len() != 1 { return Err("rust-component-fixup-argument-set"); }
        let args_index = *fixup.arguments.get("").ok_or("rust-component-fixup-argument-name")? as usize;
        let args = &self.instances[args_index];
        if args.kind != 0 || args.exports.len() != self.signatures.len() + 1
            || args.exports.get("$imports") != Some(&Value::ShimTable) {
            return Err("rust-component-private-table-binding");
        }
        let mut raw = None; let mut native = None;
        for slot in 0..self.signatures.len() as u32 {
            match args.value(&slot.to_string())? {
                Value::Raw if raw.replace(slot).is_none() => {},
                Value::Native if native.replace(slot).is_none() => {},
                Value::Raw | Value::Native | Value::Shim(_) | Value::ShimTable
                    | Value::MainTable(_) | Value::MainMemory(_) => return Err("rust-component-fixup-raw-or-provider-slot"),
                _ => {},
            }
        }
        let (raw, native) = (raw.ok_or("rust-component-raw-slot-missing")?, native.ok_or("rust-component-native-slot-missing")?);
        if self.main_imports.get(self.admission.raw as usize) != Some(&Value::Shim(raw))
            || self.main_imports.get(self.admission.admit as usize) != Some(&Value::Shim(native)) {
            return Err("rust-component-main-admission-routing");
        }
        for (index, value) in self.main_imports.iter().enumerate() {
            if *value == Value::Raw || (*value == Value::Shim(raw) && index != self.admission.raw as usize) {
                return Err("rust-component-main-raw-import-escape");
            }
        }
        if self.denied_uses.iter().any(|v| *v == Value::Raw || *v == Value::Shim(raw)) {
            return Err("rust-component-raw-or-thunk-lift-escape");
        }
        // Neither the raw primitive nor the mutable private thunk table may
        // appear in another container. No other module can consume that table.
        for (index, instance) in self.instances.iter().enumerate() {
            if instance.kind == 0 {
                for (name, value) in &instance.exports {
                    if (*value == Value::Raw || *value == Value::ShimTable) && (index != args_index
                        || (*value == Value::Raw && name != &raw.to_string())
                        || (*value == Value::ShimTable && name != "$imports")) {
                        return Err("rust-component-private-raw-or-table-escape");
                    }
                }
            }
            for argument in instance.arguments.values() {
                if *argument as usize == args_index && instance.kind != 3 {
                    return Err("rust-component-fixup-arguments-reused");
                }
            }
        }
        Ok((raw, native))
    }
}

/// Check the actual final component, not a compiler marker or supplied digest.
/// Static authentication is separate from native execution, std compatibility
/// and host feature selection. The host remains closed until those gates pass.
pub fn verify_component_routing(input: &[u8]) -> Result<ComponentRoutingReceipt, &'static str> {
    let mut graph = Graph::new(input)?; graph.scan(input)?;
    let (raw, native) = graph.finish()?;
    Ok(ComponentRoutingReceipt { component_digest: Sha256::digest(input).into(),
        main_core_digest: Sha256::digest(graph.cores[graph.main].bytes).into(),
        main_module: graph.main as u32, shim_module: graph.shim as u32, fixup_module: graph.fixup as u32,
        raw_creation_slot: raw, native_admission_slot: native,
        component_routing_authenticated: true, canonical_creation_enabled: false, standard_runtime_qualified: false })
}
