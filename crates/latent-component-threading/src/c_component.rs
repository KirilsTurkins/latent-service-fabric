//! C-only final normal-component graph authentication.
use super::*;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CComponentRoutingReceipt {
    pub component_digest: [u8; 32],
    pub original_core_digest: [u8; 32],
    pub main_core_digest: [u8; 32],
    pub main_module: u32,
    pub initialize_module: u32,
    pub raw_creation_slot: u32,
    pub native_admission_slot: u32,
    pub abi: c_abi::CCanonicalAbiReceipt,
    pub actual_component_graph_authenticated: bool,
    pub canonical_creation_enabled: bool,
    pub standard_runtime_qualified: bool,
}

fn start_shim() -> Vec<u8> {
    let mut module = Module::new();
    let mut types = TypeSection::new();
    types.ty().function([], []);
    module.section(&types);
    let mut imports = wasm_encoder::ImportSection::new();
    imports.import("", "", wasm_encoder::EntityType::Function(0));
    module.section(&imports);
    module.section(&wasm_encoder::StartSection { function_index: 0 });
    module.finish()
}

type Producers = BTreeMap<String, BTreeMap<String, String>>;

fn producer_fields(data: &[u8], offset: u64) -> Result<Producers, &'static str> {
    let reader =
        wasmparser::ProducersSectionReader::new(wasmparser::BinaryReader::new(data, offset))
            .map_err(|_| "c-component-producers")?;
    if reader.count() > 3 {
        return Err("c-component-producer-field-bound");
    }
    let mut fields = Producers::new();
    for field in reader {
        let field = field.map_err(|_| "c-component-producer-field")?;
        if field.name.len() > 1024 || field.values.count() > 64 {
            return Err("c-component-producer-value-bound");
        }
        let mut values = BTreeMap::new();
        for value in field.values {
            let value = value.map_err(|_| "c-component-producer-value")?;
            if value.name.len() > 1024 || value.version.len() > 1024 {
                return Err("c-component-producer-string-bound");
            }
            if values
                .insert(value.name.to_owned(), value.version.to_owned())
                .is_some()
            {
                return Err("c-component-duplicate-producer-value");
            }
        }
        if fields.insert(field.name.to_owned(), values).is_some() {
            return Err("c-component-duplicate-producer-field");
        }
    }
    Ok(fields)
}

// wit-bindgen0.62 emits an original metadata-only component inside the linked
// core. The normal encoder merges its two original producer identities into
// the main core; its own0.254 identity belongs to the generated shims instead.
fn generator_producers(input: &[u8]) -> Result<Producers, &'static str> {
    if input.len() > 1024 * 1024 {
        return Err("c-component-generator-metadata-bound");
    }
    let mut version = false;
    let mut encoding = false;
    let mut producers = None;
    for (index, payload) in Parser::new(0).parse_all(input).enumerate() {
        if index >= 256 {
            return Err("c-component-generator-section-bound");
        }
        match payload.map_err(|_| "c-component-generator-section")? {
            Payload::Version {
                encoding: Encoding::Component,
                ..
            } if index == 0 => version = true,
            Payload::CustomSection(section) if section.name() == "wit-component-encoding" => {
                if encoding || section.data() != [4, 0] {
                    return Err("c-component-generator-encoding");
                }
                encoding = true;
            }
            Payload::CustomSection(section) if section.name() == "producers" => {
                if producers.is_some() {
                    return Err("c-component-duplicate-generator-producers");
                }
                producers = Some(producer_fields(section.data(), section.data_offset())?);
            }
            Payload::ComponentTypeSection(_)
            | Payload::ComponentExportSection(_)
            | Payload::End(_) => {}
            _ => return Err("c-component-generator-metadata-only"),
        }
    }
    let expected = BTreeMap::from([(
        "processed-by".into(),
        BTreeMap::from([
            ("wit-component".into(), "0.259.0".into()),
            ("wit-bindgen-c".into(), "0.62.0".into()),
        ]),
    )]);
    if !version || !encoding || producers.as_ref() != Some(&expected) {
        return Err("c-component-pinned-generator-producers");
    }
    Ok(expected)
}

// Only the consumed original component-type metadata and its exact producer
// merge differ. Every other section, including executable/data bytes, is exact.
fn encoded_core_sections(input: &[u8], source: bool) -> Result<Vec<(u8, Vec<u8>)>, &'static str> {
    let mut sections = Vec::new();
    let mut producers = None;
    let mut generated = None;
    for payload in Parser::new(0).parse_all(input) {
        let payload = payload.map_err(|_| "c-component-core-section")?;
        if let Payload::CustomSection(section) = &payload {
            if section.name().starts_with("component-type") {
                if source {
                    if generated.is_some() {
                        return Err("c-component-one-generator-metadata");
                    }
                    generated = Some(generator_producers(section.data())?);
                    continue;
                }
                return Err("c-component-unconsumed-component-type");
            }
            if section.name() == "producers" {
                if producers.is_some() {
                    return Err("c-component-duplicate-producers");
                }
                producers = Some(producer_fields(section.data(), section.data_offset())?);
                continue;
            }
        }
        if let Some((id, range)) = payload.as_section() {
            let begin = usize::try_from(range.start).map_err(|_| "c-component-section-range")?;
            let end = usize::try_from(range.end).map_err(|_| "c-component-section-range")?;
            sections.push((
                id,
                input
                    .get(begin..end)
                    .ok_or("c-component-section-range")?
                    .to_vec(),
            ));
        }
    }
    let mut producers = producers.unwrap_or_default();
    if source {
        if let Some(fields) = generated {
            for (field, values) in fields {
                let original = producers.entry(field).or_default();
                for (name, value) in values {
                    if original.get(&name).is_some_and(|old| old != &value) {
                        return Err("c-component-generator-producer-conflict");
                    }
                    original.insert(name, value);
                }
            }
        } else {
            producers
                .entry("processed-by".into())
                .or_default()
                .insert("wit-component".into(), "0.254.0".into());
        }
    } else {
        let processed = producers.get("processed-by");
        let encoder = processed.and_then(|values| values.get("wit-component"));
        if encoder.map(String::as_str) != Some("0.254.0")
            && !(encoder.map(String::as_str) == Some("0.259.0")
                && processed
                    .and_then(|values| values.get("wit-bindgen-c"))
                    .map(String::as_str)
                    == Some("0.62.0"))
        {
            return Err("c-component-pinned-encoder-producer");
        }
    }
    // This final comparison value encodes the full parsed metadata, so no
    // other compiler/language field can be deleted or invented by the encoder.
    sections.push((0, format!("{producers:?}").into_bytes()));
    Ok(sections)
}

impl<'a> Graph<'a> {
    fn c_new(
        input: &'a [u8],
        expected: &[u8],
        abi: &c_abi::CCanonicalAbiReceipt,
    ) -> Result<Self, &'static str> {
        let cores = modules_with_limit(input, 4)?
            .into_iter()
            .map(core)
            .collect::<Result<Vec<_>, _>>()?;
        let matching = cores
            .iter()
            .enumerate()
            .filter(|(_, c)| {
                c.imports
                    .iter()
                    .any(|i| i.module == "$root" && i.name == NEW)
            })
            .map(|(i, _)| i)
            .collect::<Vec<_>>();
        if matching.len() != 1 {
            return Err("c-component-one-main-creator");
        }
        let main = matching[0];
        if encoded_core_sections(expected, true)?
            != encoded_core_sections(cores[main].bytes, false)?
        {
            return Err("c-component-authenticated-main-sections-mismatch");
        }
        if cores[main].nonfunction_imports
            || cores[main].exports.get("__indirect_function_table")
                != Some(&(ExternalKind::Table, 0))
            || !cores[main].local_table.is_some_and(|t| {
                t.element_type == wasmparser::RefType::FUNCREF
                    && !t.shared
                    && !t.table64
                    && t.initial <= 65536
                    && t.maximum.is_some_and(|m| m <= 65536)
            })
        {
            return Err("c-component-owned-original-table");
        }
        let expected_start = start_shim();
        let starts = cores
            .iter()
            .enumerate()
            .filter(|(_, c)| c.bytes == expected_start.as_slice())
            .map(|(i, _)| i)
            .collect::<Vec<_>>();
        if starts.len() != 1 {
            return Err("c-component-exact-encoder-start-shim");
        }
        let start_module = starts[0];
        let shims = cores
            .iter()
            .enumerate()
            .filter(|(i, c)| *i != main && *i != start_module && c.exports.contains_key("$imports"))
            .map(|(i, _)| i)
            .collect::<Vec<_>>();
        if shims.len() != 1 {
            return Err("c-component-one-private-shim");
        }
        let shim = shims[0];
        let fixup = (0..4)
            .find(|i| ![main, start_module, shim].contains(i))
            .ok_or("c-component-fixup-required")?;
        let signatures = cores[shim].shim()?;
        cores[fixup].fixup(&signatures)?;
        let find = |module: &str, name: &str| -> Result<u32, &'static str> {
            let matching = cores[main]
                .imports
                .iter()
                .enumerate()
                .filter(|(_, i)| i.module == module && i.name == name)
                .map(|(i, _)| i as u32)
                .collect::<Vec<_>>();
            if matching.len() != 1 {
                return Err("c-component-single-creator-provider-import");
            }
            Ok(matching[0])
        };
        let raw_import = find("$root", NEW)?;
        let native_import = find(NATIVE, "start")?;
        Ok(Self {
            cores,
            main,
            shim,
            fixup,
            raw_import,
            native_import,
            c: Some(CBoundary {
                start_module,
                start_instances: 0,
                root: abi.root.root_wrapper_function,
                initialize: abi.initialize_wrapper,
                realloc: abi.realloc_wrapper,
                post: abi.post_return_wrapper,
                lifted: false,
                function_types: vec![],
            }),
            signatures,
            funcs: vec![],
            tables: vec![],
            memories: vec![],
            instances: vec![],
            component_instances: vec![],
            component_funcs: vec![],
            native_imports: 0,
            main_instances: vec![],
            shim_instances: 0,
            fixup_instances: vec![],
            main_imports: vec![],
            raw_table: None,
            native_memory: None,
            denied_uses: vec![],
            raw_alias: false,
        })
    }
}

/// C-only source authentication from an actual normal encoder output. The
/// original linked core is an explicit preimage, not a custom marker trusted
/// by the host. Engine/profile selection and a real threading campaign remain
/// separate gates; no Rust verifier or existing profile is selected here.
pub fn verify_c_component_routing(
    original: &[u8],
    input: &[u8],
    public: &str,
) -> Result<CComponentRoutingReceipt, &'static str> {
    let (expected, abi) =
        c_abi::transform_c_canonical_abi(original, Sha256::digest(original).into(), public)?;
    let mut graph = Graph::c_new(input, &expected, &abi)?;
    graph.scan(input)?;
    let (raw, native) = graph.finish()?;
    Ok(CComponentRoutingReceipt {
        component_digest: Sha256::digest(input).into(),
        original_core_digest: Sha256::digest(original).into(),
        main_core_digest: Sha256::digest(graph.cores[graph.main].bytes).into(),
        main_module: graph.main as u32,
        initialize_module: graph.c.as_ref().unwrap().start_module as u32,
        raw_creation_slot: raw,
        native_admission_slot: native,
        abi,
        actual_component_graph_authenticated: true,
        canonical_creation_enabled: false,
        standard_runtime_qualified: false,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::borrow::Cow;
    use wasm_encoder::{CustomSection, ProducersField, ProducersSection};

    fn public_lift_graph(async_type: bool) -> Graph<'static> {
        Graph {
            cores: vec![],
            main: 0,
            shim: 0,
            fixup: 0,
            raw_import: 0,
            native_import: 0,
            c: Some(CBoundary {
                start_module: 0,
                start_instances: 1,
                root: 11,
                initialize: 12,
                realloc: 13,
                post: 14,
                lifted: false,
                function_types: vec![Some(async_type)],
            }),
            signatures: vec![],
            funcs: vec![
                Value::MainFunc(11),
                Value::MainFunc(13),
                Value::MainFunc(14),
            ],
            tables: vec![],
            memories: vec![Value::MainMemory(0)],
            instances: vec![],
            component_instances: vec![],
            component_funcs: vec![],
            native_imports: 0,
            main_instances: vec![],
            shim_instances: 0,
            fixup_instances: vec![],
            main_imports: vec![],
            raw_table: None,
            native_memory: None,
            denied_uses: vec![],
            raw_alias: false,
        }
    }
    fn public_lift(options: Vec<CanonicalOption>) -> CanonicalFunction {
        CanonicalFunction::Lift {
            core_func_index: 0,
            type_index: 0,
            options: options.into(),
        }
    }
    fn sync_abi_options() -> Vec<CanonicalOption> {
        vec![
            CanonicalOption::Memory(0),
            CanonicalOption::Realloc(1),
            CanonicalOption::PostReturn(2),
            CanonicalOption::UTF8,
        ]
    }
    #[test]
    fn c_public_lift_requires_declared_async_type_with_original_sync_core_abi() {
        let mut sync = public_lift_graph(false);
        assert_eq!(
            sync.canonical(public_lift(sync_abi_options())).unwrap_err(),
            "c-component-single-owned-async-type-sync-abi-lift-after-initialize"
        );
        assert!(!sync.c.as_ref().unwrap().lifted);
        let mut declared_async = public_lift_graph(true);
        declared_async
            .canonical(public_lift(sync_abi_options()))
            .unwrap();
        assert!(declared_async.c.as_ref().unwrap().lifted);
        assert_eq!(declared_async.component_funcs, vec![false]);
        assert!(
            declared_async
                .canonical(public_lift(sync_abi_options()))
                .is_err()
        );
    }
    #[test]
    fn c_declared_async_effect_does_not_enable_callback_or_async_core_abi() {
        for forbidden in [CanonicalOption::Async, CanonicalOption::Callback(0)] {
            let mut graph = public_lift_graph(true);
            let mut options = sync_abi_options();
            options.push(forbidden);
            assert_eq!(
                graph.canonical(public_lift(options)).unwrap_err(),
                "c-component-owned-sync-canonical-options"
            );
            assert!(!graph.c.as_ref().unwrap().lifted);
            assert_eq!(
                graph.options(&[forbidden]).unwrap_err(),
                "c-component-async-callback-abi-not-selected"
            );
        }
    }

    #[test]
    fn c_ready_handoff_canonical_requires_ready_aware_promote() {
        let mut selected = public_lift_graph(true);
        selected
            .canonical(CanonicalFunction::ThreadYieldThenPromote)
            .unwrap();
        assert_eq!(selected.funcs.last(), Some(&Value::CThreadPromote));
        let mut old_resume = public_lift_graph(true);
        old_resume
            .canonical(CanonicalFunction::ThreadYieldThenResume)
            .unwrap();
        assert_eq!(old_resume.funcs.last(), Some(&Value::Other));
        let mut original_rust = public_lift_graph(true);
        original_rust.c = None;
        original_rust
            .canonical(CanonicalFunction::ThreadYieldThenPromote)
            .unwrap();
        assert_eq!(original_rust.funcs.last(), Some(&Value::Other));
    }
    fn handoff_graph(name: &str, target: Value) -> Graph<'static> {
        let mut graph = public_lift_graph(true);
        graph.c.as_mut().unwrap().lifted = true;
        graph.cores = vec![Core {
            bytes: &[],
            types: vec![],
            functions: vec![],
            exports: BTreeMap::new(),
            imports: vec![
                Import {
                    module: "$root".into(),
                    name: NEW.into(),
                    function_type: 0,
                },
                Import {
                    module: NATIVE.into(),
                    name: "start".into(),
                    function_type: 0,
                },
                Import {
                    module: "$root".into(),
                    name: name.into(),
                    function_type: 0,
                },
            ],
            bodies: vec![],
            local_table: None,
            imported_table: None,
            element: None,
            unsupported_helper_sections: false,
            nonfunction_imports: false,
        }];
        graph.main_instances = vec![0];
        graph.shim_instances = 1;
        graph.fixup_instances = vec![1];
        graph.native_imports = 1;
        graph.raw_table = Some(Value::MainTable(0));
        graph.native_memory = Some(Value::MainMemory(0));
        graph.signatures = vec![
            Signature {
                params: vec![],
                results: vec![]
            };
            2
        ];
        graph.raw_import = 0;
        graph.native_import = 1;
        graph.main_imports = vec![Value::Shim(0), Value::Shim(1), target];
        graph.instances = vec![
            CoreInstance {
                kind: 0,
                arguments: BTreeMap::new(),
                exports: BTreeMap::from([
                    ("0".into(), Value::Raw),
                    ("1".into(), Value::Native),
                    ("$imports".into(), Value::ShimTable),
                ]),
            },
            CoreInstance {
                kind: 3,
                arguments: BTreeMap::from([("".into(), 0)]),
                exports: BTreeMap::new(),
            },
        ];
        graph
    }
    #[test]
    fn c_ready_handoff_final_graph_refuses_resume_or_mismatched_target() {
        assert_eq!(
            handoff_graph("[thread-yield-then-promote]", Value::CThreadPromote).finish(),
            Ok((0, 1))
        );
        assert_eq!(
            handoff_graph("[thread-yield-then-resume]", Value::CThreadPromote).finish(),
            Err("c-component-unknown-root-intrinsic")
        );
        for foreign in [Value::Other, Value::Native, Value::CThreadIndex] {
            assert_eq!(
                handoff_graph("[thread-yield-then-promote]", foreign).finish(),
                Err("c-component-canonical-context-route")
            );
        }
    }

    #[test]
    fn c_wait_canonical_functions_keep_suspend_and_deferred_resume_distinct() {
        for (function, expected) in [
            (CanonicalFunction::ThreadSuspend, Value::CThreadSuspend),
            (
                CanonicalFunction::ThreadResumeLater,
                Value::CThreadResumeLater,
            ),
            (CanonicalFunction::ThreadSuspendThenResume, Value::Other),
            (CanonicalFunction::ThreadSuspendThenPromote, Value::Other),
            (CanonicalFunction::ThreadYield, Value::Other),
        ] {
            let mut selected = public_lift_graph(true);
            selected.canonical(function).unwrap();
            assert_eq!(selected.funcs.last(), Some(&expected));
        }
        // Extending the selected C proof cannot silently extend Rust's proof.
        let mut original_rust = public_lift_graph(true);
        original_rust.c = None;
        original_rust
            .canonical(CanonicalFunction::ThreadSuspend)
            .unwrap();
        assert_eq!(original_rust.funcs.last(), Some(&Value::Other));
    }

    #[test]
    fn c_wait_final_graph_requires_the_exact_canonical_wake_target() {
        for (name, expected) in [
            ("[thread-suspend]", Value::CThreadSuspend),
            ("[thread-resume-later]", Value::CThreadResumeLater),
        ] {
            assert_eq!(handoff_graph(name, expected).finish(), Ok((0, 1)));
            for foreign in [
                Value::Other,
                Value::Native,
                Value::CThreadPromote,
                Value::CThreadIndex,
                if expected == Value::CThreadSuspend {
                    Value::CThreadResumeLater
                } else {
                    Value::CThreadSuspend
                },
            ] {
                assert_eq!(
                    handoff_graph(name, foreign).finish(),
                    Err("c-component-canonical-context-route")
                );
            }
        }
        for forbidden in [
            "[thread-suspend-then-resume]",
            "[thread-suspend-then-promote]",
            "[thread-yield]",
        ] {
            assert_eq!(
                handoff_graph(forbidden, Value::CThreadSuspend).finish(),
                Err("c-component-unknown-root-intrinsic")
            );
        }
    }

    fn metadata(version: &str, name: &str, marker: &[u8]) -> Vec<u8> {
        metadata_with_generator(version, name, marker, false)
    }
    fn metadata_with_generator(
        version: &str,
        name: &str,
        marker: &[u8],
        generator: bool,
    ) -> Vec<u8> {
        let mut module = Module::new();
        let mut types = TypeSection::new();
        types.ty().function([], []);
        module.section(&types);
        let mut producers = ProducersSection::new();
        let mut compiler = ProducersField::new();
        if !version.is_empty() {
            compiler.value("wit-component", version);
        }
        compiler.value(name, "21.1.0");
        if generator {
            compiler.value("wit-bindgen-c", "0.62.0");
        }
        producers.field("processed-by", &compiler);
        module.section(&producers);
        module.section(&CustomSection {
            name: Cow::Borrowed("owned-source"),
            data: Cow::Borrowed(marker),
        });
        module.finish()
    }
    fn generated_metadata(version: &str, encoding: &[u8]) -> Vec<u8> {
        let mut component = wasm_encoder::Component::new();
        component.section(&CustomSection {
            name: Cow::Borrowed("wit-component-encoding"),
            data: Cow::Borrowed(encoding),
        });
        let mut producers = ProducersSection::new();
        let mut compiler = ProducersField::new();
        compiler.value("wit-component", version);
        compiler.value("wit-bindgen-c", "0.62.0");
        producers.field("processed-by", &compiler);
        component.section(&producers);
        component.finish()
    }
    fn with_generated_metadata(mut core: Vec<u8>, metadata: &[u8]) -> Vec<u8> {
        use wasm_encoder::{Encode, Section};
        let section = CustomSection {
            name: Cow::Borrowed("component-type:probe"),
            data: Cow::Borrowed(metadata),
        };
        core.push(Section::id(&section));
        section.encode(&mut core);
        core
    }
    #[test]
    fn c_encoder_changes_only_the_exact_component_producer_version() {
        let source = metadata("0.259.0", "clang", b"original");
        let encoded = metadata("0.254.0", "clang", b"original");
        assert_eq!(
            encoded_core_sections(&source, true).unwrap(),
            encoded_core_sections(&encoded, false).unwrap()
        );
        assert_ne!(
            encoded_core_sections(&source, true).unwrap(),
            encoded_core_sections(&metadata("0.254.0", "foreign-compiler", b"original"), false)
                .unwrap()
        );
        assert_ne!(
            encoded_core_sections(&source, true).unwrap(),
            encoded_core_sections(&metadata("0.254.0", "clang", b"changed"), false).unwrap()
        );
        assert_eq!(
            encoded_core_sections(&metadata("0.255.0", "clang", b"original"), false).unwrap_err(),
            "c-component-pinned-encoder-producer"
        );
    }
    #[test]
    fn c_encoder_merges_only_the_original_pinned_c_generator_metadata() {
        let original = metadata("", "clang", b"original");
        let generated = generated_metadata("0.259.0", &[4, 0]);
        let source = with_generated_metadata(original, &generated);
        let encoded = metadata_with_generator("0.259.0", "clang", b"original", true);
        assert_eq!(
            encoded_core_sections(&source, true).unwrap(),
            encoded_core_sections(&encoded, false).unwrap()
        );
        for changed in [
            metadata_with_generator("0.259.0", "foreign-compiler", b"original", true),
            metadata_with_generator("0.259.0", "clang", b"changed", true),
            metadata_with_generator("0.254.0", "clang", b"original", true),
        ] {
            assert_ne!(
                encoded_core_sections(&source, true).unwrap(),
                encoded_core_sections(&changed, false).unwrap()
            );
        }
        assert!(encoded_core_sections(&metadata("0.259.0", "clang", b"original"), false).is_err());
    }
    #[test]
    fn c_generator_metadata_refuses_unknown_versions_encoding_duplicates_and_conflicts() {
        let original = metadata("", "clang", b"original");
        for generated in [
            generated_metadata("0.260.0", &[4, 0]),
            generated_metadata("0.259.0", &[3, 0]),
            metadata("0.259.0", "clang", b"not-a-component"),
        ] {
            assert!(
                encoded_core_sections(&with_generated_metadata(original.clone(), &generated), true)
                    .is_err()
            );
        }
        let generated = generated_metadata("0.259.0", &[4, 0]);
        let source = with_generated_metadata(original, &generated);
        assert_eq!(
            encoded_core_sections(&with_generated_metadata(source, &generated), true).unwrap_err(),
            "c-component-one-generator-metadata"
        );
        let conflicting =
            with_generated_metadata(metadata("0.254.0", "clang", b"original"), &generated);
        assert_eq!(
            encoded_core_sections(&conflicting, true).unwrap_err(),
            "c-component-generator-producer-conflict"
        );
    }
    #[test]
    fn c_initializer_shim_has_one_exact_original_core_start_route() {
        let original = start_shim();
        Validator::new().validate_all(&original).unwrap();
        let core = core(&original).unwrap();
        assert_eq!(core.imports.len(), 1);
        assert_eq!(core.imports[0].module, "");
        assert_eq!(core.imports[0].name, "");
        assert!(core.functions.is_empty() && core.exports.is_empty() && core.local_table.is_none());
        let mut changed = original.clone();
        let last = changed.len() - 1;
        changed[last] = 1;
        assert_ne!(changed, start_shim());
        assert!(Validator::new().validate_all(&changed).is_err());
    }
}
