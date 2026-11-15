//! Retained inbox-branch regressions for the private derived-name parser.
use super::*;

#[cfg(test)]
mod tests {
    use super::*;
    use wasm_encoder::{IndirectNameMap, NameMap, NameSection};
    use wasmparser::{BinaryReader, NameSectionReader};

    fn writer() -> RewriteAdmission {
        RewriteAdmission {
            plan: Admission {
                raw: 1,
                admit: 2,
                function: 4,
                ty: 0,
            },
            references: 0,
            derived_names: true,
        }
    }

    fn function_section(indices: &[u32]) -> NameSection {
        let mut map = NameMap::new();
        for index in indices {
            map.append(*index, "retained-name");
        }
        let mut section = NameSection::new();
        section.functions(&map);
        section
    }

    fn rewrite(section: &NameSection) -> Result<NameSection, reencode::Error<&'static str>> {
        let custom = section.as_custom();
        let reader = BinaryReader::new(custom.data.as_ref(), 0);
        writer().custom_name_section(NameSectionReader::new(reader))
    }

    #[test]
    fn moved_function_names_keep_exact_historical_order_and_mapping() {
        let named = |indices: &[u32]| {
            let mut map = NameMap::new();
            for (index, name) in indices.iter().zip(["third", "raw", "first", "native"]) {
                map.append(*index, name);
            }
            let mut section = NameSection::new();
            section.functions(&map);
            section
        };
        let section = named(&[3, 1, 0, 2]);
        let custom = section.as_custom();
        let mut reader = NameSectionReader::new(BinaryReader::new(custom.data.as_ref(), 0));
        let wasmparser::Name::Function(map) = reader.next().unwrap().unwrap() else {
            panic!("expected function names");
        };
        assert!(map.collect::<Result<Vec<_>, _>>().is_err());
        let output = rewrite(&section).unwrap();
        assert_eq!(
            output.as_custom().data,
            named(&[3, 4, 0, 2]).as_custom().data
        );
    }

    #[test]
    fn moved_local_and_label_maps_preserve_every_inner_name() {
        for labels in [false, true] {
            let mut inner = NameMap::new();
            inner.append(0, "first");
            inner.append(1, "second");
            let section = |indices: &[u32]| {
                let mut map = IndirectNameMap::new();
                for index in indices {
                    map.append(*index, &inner);
                }
                let mut names = NameSection::new();
                if labels {
                    names.labels(&map);
                } else {
                    names.locals(&map);
                }
                names
            };
            let original = section(&[3, 1, 0]);
            let output = rewrite(&original).unwrap();
            assert_eq!(
                output.as_custom().data,
                section(&[3, 4, 0]).as_custom().data
            );
        }
    }

    #[test]
    fn duplicate_and_nonexistent_function_names_are_refused() {
        for indices in [&[1, 1][..], &[4][..], &[u32::MAX][..]] {
            assert!(rewrite(&function_section(indices)).is_err());
            let mut inner = NameMap::new();
            inner.append(0, "local");
            for labels in [false, true] {
                let mut map = IndirectNameMap::new();
                for index in indices {
                    map.append(*index, &inner);
                }
                let mut names = NameSection::new();
                if labels {
                    names.labels(&map);
                } else {
                    names.locals(&map);
                }
                assert!(rewrite(&names).is_err());
            }
        }
    }

    #[test]
    fn unchanged_inner_indices_and_other_subsections_remain_strict() {
        for indices in [&[1, 0][..], &[0, 0][..]] {
            let mut inner = NameMap::new();
            for index in indices {
                inner.append(*index, "unchanged");
            }
            let mut map = IndirectNameMap::new();
            map.append(1, &inner);
            let mut names = NameSection::new();
            names.locals(&map);
            assert!(rewrite(&names).is_err());
            let mut names = NameSection::new();
            names.labels(&map);
            assert!(rewrite(&names).is_err());
            let mut names = NameSection::new();
            names.globals(&inner);
            assert!(rewrite(&names).is_err());
        }
        let mut names = function_section(&[0]);
        names.functions(&NameMap::new());
        assert!(rewrite(&names).is_err());
        assert!(
            writer()
                .custom_name_section(NameSectionReader::new(BinaryReader::new(&[1, 2, 1], 0)))
                .is_err()
        );
    }
}
