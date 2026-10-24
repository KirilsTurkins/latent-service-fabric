//! Read-only attribution from the ACTUAL emitted component, never a substitute.
//! wasmparser0.261 Parser::parse_all recursively enters component/module payloads.
//! Its ModuleSection.unchecked_range is bounds-checked before slicing below.
use serde::Serialize;
use std::collections::BTreeMap;
use wasmparser::{KnownCustom, Name, Operator, Parser, Payload, TypeRef};

const REQUIRED: [&str; 5] = [
    "runtime.lsfStackLimitExceeded",
    "runtime.stackalloc",
    "runtime.copystack",
    "runtime.newstack",
    "wit_component_export_tests_caller_api.stackFrame",
];

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Function {
    pub name: String,
    pub index: u32,
    pub start: u64,
    pub end: u64,
    pub body_digest: String,
    pub calls_cap_leaf: usize,
    pub self_calls: usize,
    pub memory_fills: usize,
    pub memory_copies: usize,
    pub checksum_copy_after_recursive_call: bool,
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Mapping {
    pub component_digest: String,
    pub core_module_digest: String,
    pub core_module_bytes: usize,
    pub static_module_index: usize,
    pub functions: Vec<Function>,
    pub numeric_cap_identity_unambiguous: bool,
}

struct Module {
    digest: String,
    bytes: usize,
    names: BTreeMap<u32, String>,
    bodies: BTreeMap<u32, (u64, u64, Vec<u8>)>,
}

fn digest(bytes: &[u8]) -> String {
    latent_artifacts::package::artifact_blob_digest(bytes).into_string()
}

fn module(raw: &[u8]) -> Module {
    let mut names = BTreeMap::new();
    let mut bodies = BTreeMap::new();
    let mut imported = 0_u32;
    let mut defined = 0_u32;
    for payload in Parser::new(0).parse_all(raw) {
        match payload.unwrap() {
            Payload::ImportSection(reader) => {
                for import in reader.into_imports() {
                    if matches!(import.unwrap().ty, TypeRef::Func(_) | TypeRef::FuncExact(_)) {
                        imported = imported.checked_add(1).unwrap();
                        assert!(imported <= 8192);
                    }
                }
            }
            Payload::CustomSection(section) => {
                if let KnownCustom::Name(reader) = section.as_known() {
                    for subsection in reader {
                        if let Name::Function(map) = subsection.unwrap() {
                            for item in map {
                                let item = item.unwrap();
                                assert!(names.len() < 8192 && item.name.len() <= 512);
                                assert!(names.insert(item.index, item.name.to_owned()).is_none());
                            }
                        }
                    }
                }
            }
            Payload::CodeSectionEntry(body) => {
                let range = body.range();
                let start = usize::try_from(range.start).unwrap();
                let end = usize::try_from(range.end).unwrap();
                assert!(start < end && end <= raw.len() && defined < 8192);
                assert!(bodies
                    .insert(
                        imported.checked_add(defined).unwrap(),
                        (range.start, range.end, raw[start..end].to_vec())
                    )
                    .is_none());
                defined += 1;
            }
            _ => (),
        }
    }
    Module {
        digest: digest(raw),
        bytes: raw.len(),
        names,
        bodies,
    }
}

pub fn inspect(component: &[u8]) -> Mapping {
    assert!(component.len() <= 16 * 1024 * 1024);
    wasmparser::Validator::new_with_features(wasmparser::WasmFeatures::all())
        .validate_all(component)
        .unwrap();
    let mut modules = vec![];
    for payload in Parser::new(0).parse_all(component) {
        if let Payload::ModuleSection {
            unchecked_range, ..
        } = payload.unwrap()
        {
            let start = usize::try_from(unchecked_range.start).unwrap();
            let end = usize::try_from(unchecked_range.end).unwrap();
            assert!(start < end && end <= component.len() && modules.len() < 16);
            modules.push(module(&component[start..end]));
        }
    }
    let candidates: Vec<_> = modules
        .iter()
        .enumerate()
        .filter(|(_, module)| {
            REQUIRED.iter().all(|name| {
                module
                    .names
                    .values()
                    .filter(|value| value.as_str() == *name)
                    .count()
                    == 1
            })
        })
        .collect();
    assert_eq!(
        candidates.len(),
        1,
        "one exact source-bound Go module is required"
    );
    let (selected, module) = candidates[0];
    let cap = *module
        .names
        .iter()
        .find(|(_, name)| name.as_str() == REQUIRED[0])
        .unwrap()
        .0;
    let mut functions = vec![];
    for name in REQUIRED {
        let index = *module
            .names
            .iter()
            .find(|(_, value)| value.as_str() == name)
            .unwrap()
            .0;
        let (start, end, body) = &module.bodies[&index];
        let reader = wasmparser::FunctionBody::new(wasmparser::BinaryReader::new(body, *start));
        let mut calls_cap_leaf = 0;
        let mut self_calls = 0;
        let mut memory_fills = 0;
        let mut memory_copies = 0;
        let mut checksum_copy_after_recursive_call = false;
        let mut operators = 0;
        for op in reader.get_operators_reader().unwrap() {
            operators += 1;
            assert!(operators <= 1_000_000);
            match op.unwrap() {
                Operator::Call { function_index } => {
                    calls_cap_leaf += usize::from(function_index == cap);
                    self_calls += usize::from(function_index == index);
                }
                Operator::MemoryFill { .. } => memory_fills += 1,
                Operator::MemoryCopy { .. } => {
                    memory_copies += 1;
                    checksum_copy_after_recursive_call |= self_calls > 0;
                }
                // A normal returned recursive call, followed by the array
                // checksum, must remain; a tail-call is not this fixture.
                Operator::ReturnCall { .. } | Operator::ReturnCallIndirect { .. } => {
                    assert_ne!(name, REQUIRED[4], "recursive frame must not be a tail call");
                }
                _ => (),
            }
        }
        if name == REQUIRED[4] {
            assert!(
                self_calls > 0
                    && memory_fills > 0
                    && memory_copies > 0
                    && checksum_copy_after_recursive_call
            );
        } else if name != REQUIRED[0] {
            assert_eq!(
                calls_cap_leaf, 1,
                "each original allocator/copy/growth guard calls the private leaf"
            );
        }
        functions.push(Function {
            name: name.into(),
            index,
            start: *start,
            end: *end,
            body_digest: digest(body),
            calls_cap_leaf,
            self_calls,
            memory_fills,
            memory_copies,
            checksum_copy_after_recursive_call,
        });
    }
    // The observer's module ordinal is first-seen IN THE BACKTRACE, not a
    // static module index. Rule out a numeric function+offset collision with
    // ANY other emitted module before using the one cap frame for attribution.
    let cap_body = &functions[0];
    for (i, other) in modules.iter().enumerate() {
        if i != selected {
            if let Some((start, end, _)) = other.bodies.get(&cap) {
                assert!(
                    *end <= cap_body.start || *start >= cap_body.end,
                    "ambiguous numeric cap identity across emitted core modules"
                );
            }
        }
    }
    Mapping {
        component_digest: digest(component),
        core_module_digest: module.digest.clone(),
        core_module_bytes: module.bytes,
        static_module_index: selected,
        functions,
        numeric_cap_identity_unambiguous: true,
    }
}

pub fn require_cap(mapping: &Mapping, snapshot: &latent_wasmtime::DevelopmentTrapSnapshot) {
    assert_eq!(snapshot.observed_errors, 1);
    assert!(!snapshot.ambiguous && !snapshot.missing_backtrace);
    assert_eq!(snapshot.engine_frame_cap, Some(16));
    assert!(snapshot.observed_frames > 0 && snapshot.observed_frames <= 16);
    assert_eq!(snapshot.trap_kind, Some("unreachable-code"));
    let cap = &mapping.functions[0];
    let matches: Vec<_> = snapshot
        .frames
        .iter()
        .flatten()
        .filter(|frame| {
            frame.function == cap.index
                && frame.module_offset.is_some_and(|offset| {
                    u64::try_from(offset)
                        .is_ok_and(|offset| cap.start <= offset && offset < cap.end)
                })
        })
        .collect();
    assert_eq!(
        matches.len(),
        1,
        "actual private cap frame, never generic GuestTrap; numeric={}",
        serde_json::to_string(snapshot).unwrap()
    );
    // Truncation of older recursive frames is explicitly preserved. The
    // required cap leaf itself must occur among the retained original frames.
}
