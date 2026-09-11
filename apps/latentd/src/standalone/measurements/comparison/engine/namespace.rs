//! Retarget maintained fixture exports without rebuilding guest code or imports.
use super::Result;
use wasm_encoder::{Component, ComponentSectionId, Encode};
use wasmparser::{BinaryReader, ComponentExternalKind};

const MAX_COMPONENT_BYTES: usize = 16 * 1024 * 1024;
const MAX_SECTIONS: usize = 4096;
const MAX_EXPORTS: usize = 8;
const MAX_NAME_BYTES: usize = 256;

struct Replacement {
    start: usize,
    end: usize,
    section: Vec<u8>,
}

/// Inputs are the already validated, hash-bound maintained fixture components.
/// Only outer exported instance names and their enclosing lengths change.
/// Nested components, core code, imports and custom sections remain byte-exact.
pub(super) fn retarget(
    base: &[u8],
    old_namespace: &str,
    tenant: &str,
    expected_exports: &[&str],
) -> Result<Vec<u8>> {
    if base.len() > MAX_COMPONENT_BYTES
        || !base.starts_with(&Component::HEADER)
        || !namespace(old_namespace)
        || !namespace(tenant)
        || expected_exports.is_empty()
        || expected_exports.len() > MAX_EXPORTS
    {
        return Err("engine namespace input bounds".into());
    }
    let prefix = format!("{old_namespace}:");
    for (index, name) in expected_exports.iter().enumerate() {
        if name.len() > MAX_NAME_BYTES
            || !name.is_ascii()
            || name
                .bytes()
                .any(|byte| byte.is_ascii_control() || byte.is_ascii_whitespace())
            || name.strip_prefix(&prefix).is_none_or(str::is_empty)
            || expected_exports[..index].contains(name)
        {
            return Err("engine namespace expected exports".into());
        }
    }
    let mut reader = BinaryReader::new(&base[Component::HEADER.len()..], Component::HEADER.len());
    let mut replacements = Vec::new();
    let mut seen = [false; MAX_EXPORTS];
    let mut sections = 0;
    while !reader.eof() {
        sections += 1;
        if sections > MAX_SECTIONS {
            return Err("engine namespace section count".into());
        }
        let start = reader.original_position();
        let id = reader.read_u8()?;
        if id > u8::from(ComponentSectionId::Export) {
            return Err("engine namespace unknown outer section".into());
        }
        let length = usize::try_from(reader.read_var_u32()?)?;
        let bytes = reader.read_bytes(length)?;
        if id == u8::from(ComponentSectionId::Export) {
            let exports = rewrite_exports(bytes, &prefix, tenant, expected_exports, &mut seen)?;
            if exports != bytes {
                // Each changed section contains at least one globally unique
                // expected export, so this list is bounded by MAX_EXPORTS.
                let mut section = vec![id];
                u32::try_from(exports.len())?.encode(&mut section);
                section.extend_from_slice(&exports);
                replacements.push(Replacement {
                    start,
                    end: reader.original_position(),
                    section,
                });
            }
        }
    }
    if seen[..expected_exports.len()].contains(&false) {
        return Err("engine namespace missing export".into());
    }
    replace(base, replacements)
}

fn replace(base: &[u8], replacements: Vec<Replacement>) -> Result<Vec<u8>> {
    let size = replacements.iter().fold(base.len(), |size, row| {
        size - (row.end - row.start) + row.section.len()
    });
    if size > MAX_COMPONENT_BYTES {
        return Err("engine namespace output byte bound".into());
    }
    let mut output = Vec::with_capacity(size);
    let mut offset = 0;
    for row in replacements {
        output.extend_from_slice(&base[offset..row.start]);
        output.extend_from_slice(&row.section);
        offset = row.end;
    }
    output.extend_from_slice(&base[offset..]);
    Ok(output)
}

fn rewrite_exports(
    bytes: &[u8],
    prefix: &str,
    tenant: &str,
    expected: &[&str],
    seen: &mut [bool; MAX_EXPORTS],
) -> Result<Vec<u8>> {
    let mut reader = BinaryReader::new(bytes, 0);
    let count = usize::try_from(reader.read_var_u32()?)?;
    if count > seen[..expected.len()].iter().filter(|seen| !**seen).count() {
        return Err("engine namespace export count".into());
    }
    // Preserve the original count, name discriminator and index encodings.
    let mut output = bytes[..reader.original_position()].to_vec();
    for _ in 0..count {
        let entry_start = reader.original_position();
        let discriminator = reader.read_u8()?;
        if discriminator > 1 {
            return Err("engine namespace export name options".into());
        }
        let name = reader.read_string()?;
        let suffix_start = reader.original_position();
        let kind: ComponentExternalKind = reader.read()?;
        reader.read_var_u32()?;
        if kind != ComponentExternalKind::Instance || reader.read_u8()? != 0 {
            return Err("engine namespace export kind or type".into());
        }
        let index = expected
            .iter()
            .position(|expected| *expected == name)
            .ok_or("engine namespace unexpected export")?;
        if seen[index] {
            return Err("engine namespace duplicate export".into());
        }
        seen[index] = true;
        let suffix = name
            .strip_prefix(prefix)
            .ok_or("engine namespace export prefix")?;
        let renamed = format!("{tenant}:{suffix}");
        if renamed.len() > MAX_NAME_BYTES {
            return Err("engine namespace renamed export bound".into());
        }
        if renamed == name {
            output.extend_from_slice(&bytes[entry_start..reader.original_position()]);
        } else {
            output.push(discriminator);
            renamed.as_str().encode(&mut output);
            output.extend_from_slice(&bytes[suffix_start..reader.original_position()]);
        }
    }
    if !reader.eof() {
        return Err("engine namespace trailing export bytes".into());
    }
    Ok(output)
}

fn namespace(value: &str) -> bool {
    let bytes = value.as_bytes();
    !bytes.is_empty()
        && bytes.len() <= 64
        && bytes[0].is_ascii_lowercase()
        && bytes.last() != Some(&b'-')
        && !bytes.windows(2).any(|pair| pair == b"--")
        && bytes
            .iter()
            .all(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit() || *byte == b'-')
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::borrow::Cow;
    use wasm_encoder::{
        ComponentExportKind, ComponentExportSection, ComponentInstanceSection, CustomSection,
    };
    use wasmparser::{Parser, Payload, Validator};

    const FIRST: &str = "tests:fixture/first@0.1.0";
    const SECOND: &str = "tests:fixture/second@0.1.0";

    fn component(exports: &ComponentExportSection) -> Vec<u8> {
        let mut component = Component::new();
        component.section(&CustomSection {
            name: Cow::Borrowed("before"),
            data: Cow::Borrowed(b"tests:fixture/raw"),
        });
        let mut instances = ComponentInstanceSection::new();
        instances.export_items(std::iter::empty::<(&str, ComponentExportKind, u32)>());
        component.section(&instances);
        component.section(exports);
        component.section(&CustomSection {
            name: Cow::Borrowed("after"),
            data: Cow::Borrowed(b"untouched"),
        });
        component.finish()
    }

    fn sections(bytes: &[u8]) -> Vec<(u8, &[u8])> {
        let mut reader = BinaryReader::new(&bytes[8..], 8);
        let mut sections = Vec::new();
        while !reader.eof() {
            let start = reader.original_position();
            let id = reader.read_u8().unwrap();
            let len = usize::try_from(reader.read_var_u32().unwrap()).unwrap();
            reader.read_bytes(len).unwrap();
            sections.push((id, &bytes[start..reader.original_position()]));
        }
        sections
    }

    #[test]
    fn only_outer_names_change_with_other_sections_and_export_indices_preserved() {
        let mut exports = ComponentExportSection::new();
        exports.export(SECOND, ComponentExportKind::Instance, 0, None);
        exports.export(FIRST, ComponentExportKind::Instance, 0, None);
        let original = component(&exports);
        Validator::new().validate_all(&original).unwrap();
        let changed = retarget(&original, "tests", "engine-a", &[FIRST, SECOND]).unwrap();
        Validator::new().validate_all(&changed).unwrap();
        for (old, new) in sections(&original).into_iter().zip(sections(&changed)) {
            assert_eq!(old.0, new.0);
            if old.0 != u8::from(ComponentSectionId::Export) {
                assert_eq!(old.1, new.1);
            }
        }
        let mut actual = Vec::new();
        for payload in Parser::new(0).parse_all(&changed) {
            if let Payload::ComponentExportSection(exports) = payload.unwrap() {
                for export in exports {
                    let export = export.unwrap();
                    actual.push(export.name.name.to_owned());
                    assert_eq!(export.kind, ComponentExternalKind::Instance);
                    assert_eq!(export.index, 0);
                    assert_eq!(export.ty, None);
                }
            }
        }
        assert_eq!(
            actual,
            [
                "engine-a:fixture/second@0.1.0",
                "engine-a:fixture/first@0.1.0"
            ]
        );
        assert_eq!(
            retarget(&original, "tests", "tests", &[FIRST, SECOND]).unwrap(),
            original
        );
    }

    #[test]
    fn rejects_unexpected_export_surface_and_malformed_component_framing() {
        let mut good = ComponentExportSection::new();
        good.export(FIRST, ComponentExportKind::Instance, 0, None);
        let original = component(&good);
        for (old, tenant, expected) in [
            ("tests", "engine-a", vec![]),
            ("tests", "engine-a", vec![SECOND]),
            ("tests", "engine-a", vec![FIRST, FIRST]),
            ("foreign", "engine-a", vec![FIRST]),
            ("tests", "bad--tenant", vec![FIRST]),
            ("tests", "Bad", vec![FIRST]),
        ] {
            assert!(retarget(&original, old, tenant, &expected).is_err());
        }
        for kind in [
            ComponentExportKind::Func,
            ComponentExportKind::Module,
            ComponentExportKind::Type,
        ] {
            let mut exports = ComponentExportSection::new();
            exports.export(FIRST, kind, 0, None);
            assert!(retarget(&component(&exports), "tests", "engine-a", &[FIRST]).is_err());
        }
        let mut duplicate = good.clone();
        duplicate.export(FIRST, ComponentExportKind::Instance, 0, None);
        assert!(retarget(
            &component(&duplicate),
            "tests",
            "engine-a",
            &[FIRST, SECOND]
        )
        .is_err());
        let mut typed = ComponentExportSection::new();
        typed.export(
            FIRST,
            ComponentExportKind::Instance,
            0,
            Some(wasm_encoder::ComponentTypeRef::Instance(0)),
        );
        assert!(retarget(&component(&typed), "tests", "engine-a", &[FIRST]).is_err());
        let mut twice = Component::new();
        twice.section(&good).section(&good);
        for bytes in [
            Component::new().finish(),
            wasm_encoder::Module::new().finish(),
            original[..original.len() - 1].to_vec(),
            twice.finish(),
            vec![0; 8],
        ] {
            assert!(retarget(&bytes, "tests", "engine-a", &[FIRST]).is_err());
        }
    }

    #[test]
    fn nested_export_and_host_import_sections_are_not_rewritten() {
        use wasm_encoder::{
            ComponentImportSection, ComponentTypeRef, ComponentTypeSection, InstanceType, Module,
            ModuleSection, RawSection,
        };
        let mut exports = ComponentExportSection::new();
        exports.export(FIRST, ComponentExportKind::Instance, 0, None);
        let nested = component(&exports);
        let mut outer = Component::new();
        let mut types = ComponentTypeSection::new();
        types.instance(&InstanceType::new());
        outer.section(&types);
        let mut imports = ComponentImportSection::new();
        imports.import("latent:host/service@0.1.0", ComponentTypeRef::Instance(0));
        outer.section(&imports);
        outer.section(&ModuleSection(&Module::new()));
        outer.section(&RawSection {
            id: u8::from(ComponentSectionId::Component),
            data: &nested,
        });
        outer.section(&exports);
        let original = outer.finish();
        Validator::new().validate_all(&original).unwrap();
        let changed = retarget(&original, "tests", "engine-b", &[FIRST]).unwrap();
        Validator::new().validate_all(&changed).unwrap();
        let before = sections(&original);
        let after = sections(&changed);
        assert_eq!(before.len(), after.len());
        for (old, new) in before.into_iter().zip(after) {
            if old.0 != u8::from(ComponentSectionId::Export) {
                assert_eq!(old, new);
            }
        }
    }

    #[test]
    fn preserves_legacy_name_discriminator_and_noncanonical_index_bytes() {
        let mut payload = vec![1, 1];
        FIRST.encode(&mut payload);
        payload.extend_from_slice(&[5, 0x80, 0, 0]);
        let changed = rewrite_exports(
            &payload,
            "tests:",
            "engine-b",
            &[FIRST],
            &mut [false; MAX_EXPORTS],
        )
        .unwrap();
        assert_eq!(changed[1], 1);
        assert!(changed.ends_with(&[5, 0x80, 0, 0]));
        let mut options = payload.clone();
        options[1] = 2;
        assert!(rewrite_exports(
            &options,
            "tests:",
            "engine-b",
            &[FIRST],
            &mut [false; MAX_EXPORTS]
        )
        .is_err());
        payload.push(0);
        assert!(rewrite_exports(
            &payload,
            "tests:",
            "engine-b",
            &[FIRST],
            &mut [false; MAX_EXPORTS]
        )
        .is_err());
    }

    #[test]
    fn split_exports_keep_interleaved_instance_indices_and_global_name_bijection() {
        let split = |second| {
            let mut component = Component::new();
            let mut instances = ComponentInstanceSection::new();
            instances.export_items(std::iter::empty::<(&str, ComponentExportKind, u32)>());
            component.section(&instances);
            let mut first = ComponentExportSection::new();
            first.export(FIRST, ComponentExportKind::Instance, 0, None);
            component.section(&first);
            // Exporting the first instance creates index 1. This interleaved
            // definition is index 2; moving/combining exports changes meaning.
            component.section(&instances);
            let mut last = ComponentExportSection::new();
            last.export(second, ComponentExportKind::Instance, 2, None);
            component.section(&last);
            component.section(&ComponentExportSection::new());
            component.finish()
        };
        let original = split(SECOND);
        Validator::new().validate_all(&original).unwrap();
        let changed = retarget(&original, "tests", "engine-b", &[FIRST, SECOND]).unwrap();
        Validator::new().validate_all(&changed).unwrap();
        let before = sections(&original);
        let after = sections(&changed);
        assert_eq!(before.len(), after.len());
        for (old, new) in before.iter().zip(&after) {
            assert_eq!(old.0, new.0);
            if old.0 != u8::from(ComponentSectionId::Export) {
                assert_eq!(old.1, new.1);
            }
        }
        assert_eq!(
            before.last(),
            after.last(),
            "empty export section is byte-exact"
        );
        let indices: Vec<_> = Parser::new(0)
            .parse_all(&changed)
            .filter_map(|payload| {
                if let Payload::ComponentExportSection(exports) = payload.unwrap() {
                    Some(
                        exports
                            .into_iter()
                            .map(|export| export.unwrap().index)
                            .collect::<Vec<_>>(),
                    )
                } else {
                    None
                }
            })
            .collect();
        assert_eq!(indices, [vec![0], vec![2], vec![]]);
        assert!(retarget(&split(FIRST), "tests", "engine-b", &[FIRST, SECOND]).is_err());
        assert!(retarget(&original, "tests", "engine-b", &[FIRST]).is_err());
        assert_eq!(
            retarget(&original, "tests", "tests", &[FIRST, SECOND]).unwrap(),
            original
        );
    }
}
