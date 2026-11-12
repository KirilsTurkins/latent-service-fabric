//! Compatibility for name rows in an internally derived, authenticated core.
//!
//! Root wrapping moves original bodies to appended indices. The frozen Rust
//! derivations retain the original name-row order, which is no longer monotonic
//! after that remap. Do not sort those rows: their bytes are part of the complete
//! source proof. This helper is not used by the public linked-core transform.
use wasm_encoder::{
    IndirectNameMap, NameMap, NameSection,
    reencode::{self, Reencode},
};
use wasmparser::Name;

type Error = reencode::Error<&'static str>;

fn seen(functions: u32) -> Result<Vec<bool>, Error> {
    if functions > super::MAX_FUNCTIONS {
        return Err(Error::UserError("rust-derived-name-function-bound"));
    }
    let mut seen = Vec::new();
    seen.try_reserve_exact(functions as usize)
        .map_err(|_| Error::UserError("rust-derived-name-allocation"))?;
    seen.resize(functions as usize, false);
    Ok(seen)
}

fn claim(seen: &mut [bool], index: u32) -> Result<(), Error> {
    let entry = seen
        .get_mut(index as usize)
        .ok_or(Error::UserError("rust-derived-name-function-bound"))?;
    if std::mem::replace(entry, true) {
        return Err(Error::UserError("rust-derived-name-duplicate"));
    }
    Ok(())
}

pub(super) fn subsection(
    rewrite: &mut super::RewriteAdmission,
    output: &mut NameSection,
    name: Name<'_>,
) -> Result<(), Error> {
    match name {
        Name::Function(map) => {
            let mut seen = seen(rewrite.plan.function)?;
            let mut names = NameMap::new();
            // Use the raw, syntax-checked rows only here. The original function
            // domain and uniqueness remain bounded; only row order is retained.
            for row in map.names {
                let row = row?;
                claim(&mut seen, row.index)?;
                names.append(rewrite.function_index(row.index)?, row.name);
            }
            output.functions(&names);
        }
        Name::Local(map) => {
            output.locals(&indirect(rewrite, map)?);
        }
        Name::Label(map) => {
            output.labels(&indirect(rewrite, map)?);
        }
        other => reencode::utils::parse_custom_name_subsection(rewrite, output, other)?,
    }
    Ok(())
}

fn indirect(
    rewrite: &mut super::RewriteAdmission,
    map: wasmparser::IndirectNameMap<'_>,
) -> Result<IndirectNameMap, Error> {
    let mut seen = seen(rewrite.plan.function)?;
    let mut names = IndirectNameMap::new();
    for row in map.names {
        let row = row?;
        claim(&mut seen, row.index)?;
        // Inner local/label indices are never remapped. Keep the current
        // parser's ordering, duplicate and encoding checks for these maps.
        let inner = reencode::utils::name_map(row.names, Ok)?;
        names.append(rewrite.function_index(row.index)?, &inner);
    }
    Ok(names)
}
