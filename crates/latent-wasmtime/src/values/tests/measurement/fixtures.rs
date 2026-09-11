use std::collections::BTreeMap;

use wasmtime::component::{types::ComponentItem, Component, Type};
use wasmtime::{Config, Engine};

use super::ProbeResult;

pub(super) const TYPE_FIXTURE: &[u8] = include_bytes!("../../types.wasm");

pub(super) struct Fixture {
    pub types: Vec<Type>,
    pub input: Vec<u8>,
    pub expected: Vec<u8>,
}

impl Fixture {
    pub fn new(family: &str) -> ProbeResult<Self> {
        // This owned type-only component creates no guest Store or Instance.
        // Unlike the portable tests' OnceLock, all selected Type owners below
        // can be dropped explicitly before this collector's final receipt.
        let mut config = Config::new();
        config.wasm_component_model(true);
        let engine = Engine::new(&config)?;
        let component = Component::new(&engine, TYPE_FIXTURE)?;
        let mut types = BTreeMap::new();
        for (name, export) in component.component_type().exports(&engine) {
            let ComponentItem::Type(ty) = export.ty else {
                return Err("codec fixture contains a non-type export".into());
            };
            types.insert(name.to_owned(), ty);
        }
        let selected = |name: &str| -> ProbeResult<Type> {
            types
                .get(name)
                .cloned()
                .ok_or_else(|| "missing codec fixture type".into())
        };
        let (types, input, expected) = match family {
            "scalar-params" => {
                let input = r#"[true,255,65535,4294967295,-128,-32768,-2147483648,"18446744073709551615","-9223372036854775808","0.1","-0","\ud83d\ude80","hello"]"#;
                let expected = input.replace(r"\ud83d\ude80", "\u{1f680}");
                (
                    vec![
                        Type::Bool,
                        Type::U8,
                        Type::U16,
                        Type::U32,
                        Type::S8,
                        Type::S16,
                        Type::S32,
                        Type::U64,
                        Type::S64,
                        Type::Float32,
                        Type::Float64,
                        Type::Char,
                        Type::String,
                    ],
                    input.to_owned(),
                    expected,
                )
            }
            "byte-list" => {
                let input = format!(
                    "[[{}]]",
                    (0..4096)
                        .map(|i| (i % 256).to_string())
                        .collect::<Vec<_>>()
                        .join(",")
                );
                (vec![selected("list")?], input.clone(), input)
            }
            "nested-record" => {
                let raw = r#"{"c":{"count":3,"name":"c"},"b":{"count":2,"name":"b"},"a":{"count":1,"name":"a"}}"#;
                let canonical = r#"{"a":{"name":"a","count":1},"b":{"name":"b","count":2},"c":{"name":"c","count":3}}"#;
                let tail_in = r#",{"value":"9","case":"number"},["admin","read"],{"some":{"some":"nested"}},{"err":{"value":"7","case":"number"}},[{"ok":"done"},{"err":{"value":"7","case":"number"}},{"err":{"case":"empty"}}]]"#;
                let tail_out = r#",{"case":"number","value":"9"},["read","admin"],{"some":{"some":"nested"}},{"err":{"case":"number","value":"7"}},[{"ok":"done"},{"err":{"case":"number","value":"7"}},{"err":{"case":"empty"}}]]"#;
                (
                    vec![
                        selected("wide-list")?,
                        selected("variant")?,
                        selected("flags")?,
                        selected("nested")?,
                        selected("result")?,
                        selected("nested-result")?,
                    ],
                    format!("[[{}]{}", [raw; 32].join(","), tail_in),
                    format!("[[{}]{}", [canonical; 32].join(","), tail_out),
                )
            }
            "string-64k" | "string-near-limit" => {
                let size = if family == "string-64k" {
                    65_536
                } else {
                    122_880
                };
                let input = format!("[\"{}\"]", "a".repeat(size));
                (vec![Type::String], input.clone(), input)
            }
            "escaped-unicode" => {
                let input = format!("[\"{}\"]", r#"\ud83d\ude80\n\"\\\u00e9"#.repeat(4096));
                let expected = format!("[\"{}\"]", "\u{1f680}\\n\\\"\\\\\u{e9}".repeat(4096));
                (vec![Type::String], input, expected)
            }
            _ => return Err("unknown codec family".into()),
        };
        Ok(Self {
            types,
            input: input.into_bytes(),
            expected: expected.into_bytes(),
        })
    }
}
