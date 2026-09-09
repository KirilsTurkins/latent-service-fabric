use std::fmt;

use serde::de::{self, DeserializeSeed, SeqAccess, Visitor};
use wasmtime::component::{types, Type, Val};

use super::{invalid, node_bytes, text, RejectExtra, Seed, State};

pub(super) struct Params<'a> {
    pub(super) state: &'a mut State,
    pub(super) types: &'a [Type],
}

impl<'de> DeserializeSeed<'de> for Params<'_> {
    type Value = Vec<Val>;

    fn deserialize<D: de::Deserializer<'de>>(self, deserializer: D) -> Result<Vec<Val>, D::Error> {
        deserializer.deserialize_seq(self)
    }
}

impl<'de> Visitor<'de> for Params<'_> {
    type Value = Vec<Val>;

    fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("the bounded component parameter array")
    }

    fn visit_seq<A: SeqAccess<'de>>(self, mut sequence: A) -> Result<Vec<Val>, A::Error> {
        self.state.charge(node_bytes())?;
        self.state.prepay(self.types.len())?;
        let mut output = Vec::new();
        self.state.reserve(&mut output, self.types.len())?;
        for ty in self.types {
            let value = sequence
                .next_element_seed(Seed {
                    state: self.state,
                    ty,
                    depth: 1,
                    prepaid: true,
                })?
                .ok_or_else(invalid)?;
            output.push(value);
        }
        sequence.next_element_seed(RejectExtra)?;
        Ok(output)
    }
}

pub(super) fn list<'de, A: SeqAccess<'de>>(
    state: &mut State,
    list: &types::List,
    mut sequence: A,
    depth: usize,
) -> Result<Val, A::Error> {
    let ty = list.ty();
    let mut output = Vec::new();
    loop {
        if output.len() == state.limits.max_collection_items {
            sequence.next_element_seed(RejectExtra)?;
            break;
        }
        let Some(value) = sequence.next_element_seed(Seed {
            state,
            ty: &ty,
            depth: depth + 1,
            prepaid: false,
        })?
        else {
            break;
        };
        state.push(&mut output, value)?;
    }
    Ok(Val::List(output))
}

pub(super) fn tuple<'de, A: SeqAccess<'de>>(
    state: &mut State,
    tuple: &types::Tuple,
    mut sequence: A,
    depth: usize,
) -> Result<Val, A::Error> {
    let types = tuple.types();
    state.prepay(types.len())?;
    let mut output = Vec::new();
    state.reserve(&mut output, types.len())?;
    for ty in types {
        let value = sequence
            .next_element_seed(Seed {
                state,
                ty: &ty,
                depth: depth + 1,
                prepaid: true,
            })?
            .ok_or_else(invalid)?;
        output.push(value);
    }
    sequence.next_element_seed(RejectExtra)?;
    Ok(Val::Tuple(output))
}

pub(super) fn flags<'de, A: SeqAccess<'de>>(
    state: &mut State,
    flags: &types::Flags,
    mut sequence: A,
) -> Result<Val, A::Error> {
    // This scratch is proportional to selected names, not the declaration's
    // width. Both vectors fit within the unchanged per-selected-flag node charge.
    let mut selected = Vec::new();
    loop {
        if selected.len() == state.limits.max_collection_items {
            sequence.next_element_seed(RejectExtra)?;
            break;
        }
        let Some(name) = sequence.next_element_seed(text::Text {
            state,
            charged: true,
        })?
        else {
            break;
        };
        state.charge(node_bytes())?;
        let index = flags
            .names()
            .position(|declared| declared == name.as_ref())
            .ok_or_else(invalid)?;
        let owned = text::own(state, name)?;
        state.push(&mut selected, (index, owned))?;
    }
    selected.sort_unstable_by_key(|(index, _)| *index);
    if selected.windows(2).any(|pair| pair[0].0 == pair[1].0) {
        return Err(invalid());
    }
    let mut output = Vec::new();
    state.reserve(&mut output, selected.len())?;
    for (_, name) in selected {
        output.push(name);
    }
    Ok(Val::Flags(output))
}
