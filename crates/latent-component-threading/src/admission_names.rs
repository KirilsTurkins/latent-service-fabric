//! Preserve historical root-clone name metadata without weakening core validation.
use super::RewriteAdmission;
use std::collections::BTreeSet;
use wasm_encoder::reencode::{self, Reencode};
use wasm_encoder::{IndirectNameMap, NameMap, NameSection};
use wasmparser::Name;

impl RewriteAdmission {
    fn named_function(
        &mut self,
        index: u32,
        seen: &mut BTreeSet<u32>,
    ) -> Result<u32, reencode::Error<&'static str>> {
        // The appended admission body does not exist in the input. This also
        // bounds the set independently of an untrusted name-map count.
        if index >= self.plan.function || !seen.insert(index) {
            return Err(reencode::Error::UserError(
                "rust-child-admission-name-function-index",
            ));
        }
        self.function_index(index)
    }

    fn indirect_names(
        &mut self,
        map: wasmparser::IndirectNameMap<'_>,
    ) -> Result<IndirectNameMap, reencode::Error<&'static str>> {
        let mut result = IndirectNameMap::new();
        let mut seen = BTreeSet::new();
        for row in map.names {
            let row = row?;
            let index = self.named_function(row.index, &mut seen)?;
            let mut inner = NameMap::new();
            // Root cloning only remaps the outer function index. Inner local
            // and label indices retain the parser's strict ordering checks.
            for name in row.names {
                let name = name?;
                inner.append(name.index, name.name);
            }
            result.append(index, &inner);
        }
        Ok(result)
    }

    pub(super) fn parse_names(
        &mut self,
        names: &mut NameSection,
        section: Name<'_>,
    ) -> Result<(), reencode::Error<&'static str>> {
        // Root/allocator clones move function indices to the end but retain
        // the original descriptive row order. wasmparser 0.262's NameMap
        // iterator rejects that historical order. Read only these outer
        // function rows through the checked raw iterator, retaining exact
        // catalogue bytes and the same remapping. Duplicate/out-of-range
        // indices, malformed strings and truncated maps still fail closed.
        // These names grant no authority; code, imports, wrapper bodies and
        // whole-component byte authentication are checked independently.
        match section {
            Name::Function(map) => {
                let mut result = NameMap::new();
                let mut seen = BTreeSet::new();
                for row in map.names {
                    let row = row?;
                    let index = self.named_function(row.index, &mut seen)?;
                    result.append(index, row.name);
                }
                names.functions(&result);
                Ok(())
            }
            Name::Local(map) => {
                names.locals(&self.indirect_names(map)?);
                Ok(())
            }
            Name::Label(map) => {
                names.labels(&self.indirect_names(map)?);
                Ok(())
            }
            other => reencode::utils::parse_custom_name_subsection(self, names, other),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::admission::Admission;
    use std::borrow::Cow;
    use wasm_encoder::{CustomSection, Module};
    use wasmparser::Parser;

    fn rewrite(input: &[u8]) -> Result<(Vec<u8>, u64), reencode::Error<&'static str>> {
        let mut rewrite = RewriteAdmission {
            plan: Admission {
                raw: 1,
                admit: 2,
                function: 4,
                ty: 0,
            },
            references: 0,
        };
        let mut output = Module::new();
        rewrite.parse_core_module(&mut output, Parser::new(0), input)?;
        Ok((output.finish(), rewrite.references))
    }

    fn fixture(kind: u8, indices: &[u32], inner_indices: &[u32]) -> Vec<u8> {
        let mut names = NameSection::new();
        if kind == 1 {
            let mut map = NameMap::new();
            for index in indices {
                map.append(*index, "original-name");
            }
            names.functions(&map);
        } else {
            let mut map = IndirectNameMap::new();
            for index in indices {
                let mut inner = NameMap::new();
                for local in inner_indices {
                    inner.append(*local, "original-inner-name");
                }
                map.append(*index, &inner);
            }
            match kind {
                2 => names.locals(&map),
                3 => names.labels(&map),
                _ => unreachable!(),
            };
        }
        let mut module = Module::new();
        module.section(&names);
        module.finish()
    }

    #[test]
    fn root_clone_name_order_preserves_exact_bytes_and_function_remapping() {
        for kind in [1, 2, 3] {
            let input = fixture(kind, &[3, 1, 2, 0], &[0, 1]);
            let expected = fixture(kind, &[3, 4, 2, 0], &[0, 1]);
            let (output, references) = rewrite(&input).unwrap();
            assert_eq!(output, expected);
            assert_eq!(references, 1);
        }
    }

    #[test]
    fn duplicate_and_out_of_range_function_names_are_rejected() {
        for kind in [1, 2, 3] {
            for indices in [[3, 3], [4, 0], [u32::MAX, 0]] {
                let input = fixture(kind, &indices, &[0]);
                assert!(matches!(
                    rewrite(&input),
                    Err(reencode::Error::UserError(
                        "rust-child-admission-name-function-index"
                    ))
                ));
            }
        }
    }

    #[test]
    fn inner_indices_are_not_relaxed_by_outer_function_remapping() {
        for kind in [2, 3] {
            for indices in [[1, 0], [0, 0]] {
                let input = fixture(kind, &[3, 1], &indices);
                assert!(matches!(rewrite(&input), Err(reencode::Error::ParseError(_))));
            }
        }
    }

    #[test]
    fn truncated_function_names_are_not_copied_as_opaque_metadata() {
        let mut module = Module::new();
        module.section(&CustomSection {
            name: Cow::Borrowed("name"),
            // Function subsection: one row, index 3, missing one name byte.
            data: Cow::Borrowed(&[1, 3, 1, 3, 1]),
        });
        assert!(matches!(
            rewrite(&module.finish()),
            Err(reencode::Error::ParseError(_))
        ));
    }
}
