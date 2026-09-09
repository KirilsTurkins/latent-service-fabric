use std::borrow::Cow;

use serde::de::MapAccess;
use wasmtime::component::{types, Val};

use super::{invalid, text, RejectExtra, Seed, State};

pub(super) fn record<'de, A: MapAccess<'de>>(
    state: &mut State,
    record: &types::Record,
    mut object: A,
    depth: usize,
) -> Result<Val, A::Error> {
    let width = record.fields().len();
    state.prepay(width)?;
    let mut output = Vec::new();
    let mut fields = Vec::new();
    state.reserve(&mut output, width)?;
    state.reserve(&mut fields, width)?;
    output.resize_with(width, || (String::new(), Val::Bool(false)));
    // One bounded declaration index avoids scanning/recreating every field Type
    // for each input key. Its slots and the final output slots fit within the
    // existing conservative node charge; they add no new acceptance charge.
    for (index, field) in record.fields().enumerate() {
        fields.push((index, field, false));
    }
    fields.sort_unstable_by(|left, right| left.1.name.cmp(right.1.name));

    let mut count = 0;
    while let Some(name) = next_key(state, &mut object, count)? {
        let position = fields
            .binary_search_by(|(_, field, _)| field.name.cmp(name.as_ref()))
            .map_err(|_| invalid())?;
        let (index, field, seen) = &mut fields[position];
        if *seen {
            return Err(invalid());
        }
        *seen = true;
        state.text(&name)?;
        let name = text::own(state, name)?;
        let value = object.next_value_seed(Seed {
            state,
            ty: &field.ty,
            depth: depth + 1,
            prepaid: true,
        })?;
        output[*index] = (name, value);
        count += 1;
    }
    if count != width {
        return Err(invalid());
    }
    Ok(Val::Record(output))
}

pub(super) fn next_key<'de, A: MapAccess<'de>>(
    state: &mut State,
    object: &mut A,
    count: usize,
) -> Result<Option<Cow<'de, str>>, A::Error> {
    if count == state.limits.max_collection_items {
        object.next_key_seed(RejectExtra)?;
        Ok(None)
    } else {
        object.next_key_seed(text::Text {
            state,
            charged: false,
        })
    }
}
