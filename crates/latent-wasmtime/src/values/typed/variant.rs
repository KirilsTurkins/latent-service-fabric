use serde::de::{self, DeserializeSeed, MapAccess};
use serde_json::value::RawValue;
use wasmtime::component::{types, Type, Val};

use super::{invalid, records::next_key, text, Seed, State};

pub(super) fn variant<'de, A: MapAccess<'de>>(
    state: &mut State,
    variant: &types::Variant,
    mut object: A,
    depth: usize,
) -> Result<Val, A::Error> {
    let mut name = None;
    let mut payload_type = None;
    let mut payload = None;
    let mut deferred = None;
    let mut saw_value = false;
    let mut count = 0;
    while let Some(key) = next_key(state, &mut object, count)? {
        match key.as_ref() {
            "case" if name.is_none() => {
                let case = object.next_value_seed(text::Text {
                    state,
                    charged: true,
                })?;
                let declared = variant
                    .cases()
                    .find(|declared| declared.name == case.as_ref())
                    .ok_or_else(invalid)?;
                payload_type = declared.ty;
                name = Some(text::own(state, case)?);
                if let Some(raw) = deferred.take() {
                    let ty = payload_type.as_ref().ok_or_else(invalid)?;
                    payload = Some(Box::new(decode_deferred(state, ty, raw, depth + 1)?));
                }
            }
            "value" if !saw_value => {
                saw_value = true;
                if name.is_some() {
                    let ty = payload_type.as_ref().ok_or_else(invalid)?;
                    payload = Some(Box::new(object.next_value_seed(Seed {
                        state,
                        ty,
                        depth: depth + 1,
                        prepaid: false,
                    })?));
                } else {
                    // Only this input order needs a raw span. RawValue checks
                    // syntax, not our duplicate/collection/type rules; the
                    // selected typed seed must subsequently consume the span.
                    deferred = Some(object.next_value::<&'de RawValue>()?);
                }
            }
            _ => return Err(invalid()),
        }
        count += 1;
    }
    let name = name.ok_or_else(invalid)?;
    if payload_type.is_some() != saw_value {
        return Err(invalid());
    }
    Ok(Val::Variant(name, payload))
}

fn decode_deferred<E: de::Error>(
    state: &mut State,
    ty: &Type,
    raw: &RawValue,
    depth: usize,
) -> Result<Val, E> {
    let mut deserializer = serde_json::Deserializer::from_slice(raw.get().as_bytes());
    let value = Seed {
        state,
        ty,
        depth,
        prepaid: false,
    }
    .deserialize(&mut deserializer)
    .map_err(|_| invalid())?;
    deserializer.end().map_err(|_| invalid())?;
    Ok(value)
}
