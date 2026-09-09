use std::fmt;

use serde::de::{self, DeserializeSeed, MapAccess, Visitor};
use wasmtime::component::{types, Type, Val};

use super::{invalid, records::next_key, RejectExtra, Seed, State};

pub(super) fn option<'de, A: MapAccess<'de>>(
    state: &mut State,
    option: &types::OptionType,
    mut object: A,
    depth: usize,
) -> Result<Val, A::Error> {
    let tag = next_key(state, &mut object, 0)?.ok_or_else(invalid)?;
    let value = match tag.as_ref() {
        "none" => {
            object.next_value_seed(Null)?;
            None
        }
        "some" => Some(Box::new(object.next_value_seed(Seed {
            state,
            ty: &option.ty(),
            depth: depth + 1,
            prepaid: false,
        })?)),
        _ => return Err(invalid()),
    };
    object.next_key_seed(RejectExtra)?;
    Ok(Val::Option(value))
}

pub(super) fn result<'de, A: MapAccess<'de>>(
    state: &mut State,
    result: &types::ResultType,
    mut object: A,
    depth: usize,
) -> Result<Val, A::Error> {
    let tag = next_key(state, &mut object, 0)?.ok_or_else(invalid)?;
    let value = match tag.as_ref() {
        "ok" => Ok(branch(state, result.ok(), &mut object, depth + 1)?),
        "err" => Err(branch(state, result.err(), &mut object, depth + 1)?),
        _ => return Err(invalid()),
    };
    object.next_key_seed(RejectExtra)?;
    Ok(Val::Result(value))
}

fn branch<'de, A: MapAccess<'de>>(
    state: &mut State,
    ty: Option<Type>,
    object: &mut A,
    depth: usize,
) -> Result<Option<Box<Val>>, A::Error> {
    match ty {
        Some(ty) => object
            .next_value_seed(Seed {
                state,
                ty: &ty,
                depth,
                prepaid: false,
            })
            .map(|value| Some(Box::new(value))),
        None => object.next_value_seed(Null).map(|()| None),
    }
}

struct Null;

impl<'de> DeserializeSeed<'de> for Null {
    type Value = ();

    fn deserialize<D: de::Deserializer<'de>>(self, deserializer: D) -> Result<(), D::Error> {
        deserializer.deserialize_unit(self)
    }
}

impl Visitor<'_> for Null {
    type Value = ();

    fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("null for a unit component branch")
    }

    fn visit_unit<E: de::Error>(self) -> Result<(), E> {
        Ok(())
    }
}
