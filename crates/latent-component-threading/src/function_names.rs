//! Preserve authenticated historical name-map order across admission rewriting.
//! Earlier owned root rewrites move cleanup/allocator names to appended indices
//! without sorting. wasmparser 0.262 rejects that order in its NameMap iterator.
//! Decode its underlying bounded entries instead: full byte identity remains
//! enforced by the original-source/component verifier, including these names.
//! This is metadata compatibility, never executable authority or relaxed code
//! validation. Duplicate indices, collisions and malformed encodings still fail.
use super::*;

type Error = reencode::Error<&'static str>;

fn preserved<T>(
    entries: impl IntoIterator<Item = Result<(u32, T), Error>>,
    remappings: &[(u32, u32)],
) -> Result<Vec<(u32, T)>, Error> {
    let mut output = Vec::new();
    let mut original_indices = std::collections::BTreeSet::new();
    let mut mapped_indices = std::collections::BTreeSet::new();
    for entry in entries {
        let (original, value) = entry?;
        if output.len() >= MAX_FUNCTIONS as usize || !original_indices.insert(original) {
            return Err(Error::UserError("function-name-input-duplicate-or-bound"));
        }
        let mapped = remappings
            .iter()
            .find_map(|&(from, to)| (from == original).then_some(to))
            .unwrap_or(original);
        if !mapped_indices.insert(mapped) {
            return Err(Error::UserError("function-name-remap-collision"));
        }
        output.push((mapped, value));
    }
    Ok(output)
}

pub(super) fn parse<T: Reencode<Error = &'static str>>(
    reencoder: &mut T,
    names: &mut wasm_encoder::NameSection,
    section: wasmparser::Name<'_>,
    remappings: &[(u32, u32)],
) -> Result<(), Error> {
    let locals = matches!(section, wasmparser::Name::Local(_));
    match section {
        wasmparser::Name::Function(map) => {
            let entries = map.names.map(|entry| {
                let entry = entry?;
                Ok((entry.index, entry.name))
            });
            let mut output = wasm_encoder::NameMap::new();
            for (index, name) in preserved(entries, remappings)? {
                output.append(index, name);
            }
            names.functions(&output);
        }
        wasmparser::Name::Local(map) | wasmparser::Name::Label(map) => {
            let entries = map.names.map(|entry| {
                let entry = entry?;
                // Local and label indices are unchanged within the moved body.
                let inner = reencode::utils::name_map(entry.names, Ok)?;
                Ok((entry.index, inner))
            });
            let mut output = wasm_encoder::IndirectNameMap::new();
            for (index, inner) in preserved(entries, remappings)? {
                output.append(index, &inner);
            }
            if locals {
                names.locals(&output);
            } else {
                names.labels(&output);
            }
        }
        other => reencode::utils::parse_custom_name_subsection(reencoder, names, other)?,
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn legacy_order_and_non_monotonic_remaps_preserve_every_name() {
        let entries = [
            (0, "context"),
            (14, "post"),
            (13, "realloc"),
            (2, "creation"),
            (11, "tail"),
        ];
        assert_eq!(
            preserved(entries.into_iter().map(Ok), &[(2, 15)]).unwrap(),
            [
                (0, "context"),
                (14, "post"),
                (13, "realloc"),
                (15, "creation"),
                (11, "tail"),
            ]
        );
    }

    #[test]
    fn duplicate_input_and_remap_collisions_are_not_silently_dropped() {
        assert!(preserved([(1, "a"), (1, "b")].into_iter().map(Ok), &[]).is_err());
        assert!(preserved([(1, "a"), (2, "b")].into_iter().map(Ok), &[(1, 2)]).is_err());
        assert!(preserved([(1, "a"), (2, "b")].into_iter().map(Ok), &[(1, 3), (2, 3)]).is_err());
        assert!(preserved((0..=MAX_FUNCTIONS).map(|index| Ok((index, "name"))), &[]).is_err());
    }
}
