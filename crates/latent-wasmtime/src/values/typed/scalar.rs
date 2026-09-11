use serde::de;
use wasmtime::component::{Type, Val};

use super::{super::decode, invalid, State};

pub(super) fn signed<E: de::Error>(ty: &Type, value: i64) -> Result<Val, E> {
    match ty {
        Type::S8 => i8::try_from(value).map(Val::S8).map_err(|_| invalid()),
        Type::S16 => i16::try_from(value).map(Val::S16).map_err(|_| invalid()),
        Type::S32 => i32::try_from(value).map(Val::S32).map_err(|_| invalid()),
        Type::U8 => u8::try_from(value).map(Val::U8).map_err(|_| invalid()),
        Type::U16 => u16::try_from(value).map(Val::U16).map_err(|_| invalid()),
        Type::U32 => u32::try_from(value).map(Val::U32).map_err(|_| invalid()),
        _ => Err(invalid()),
    }
}

pub(super) fn unsigned<E: de::Error>(ty: &Type, value: u64) -> Result<Val, E> {
    match ty {
        Type::S8 => i8::try_from(value).map(Val::S8).map_err(|_| invalid()),
        Type::S16 => i16::try_from(value).map(Val::S16).map_err(|_| invalid()),
        Type::S32 => i32::try_from(value).map(Val::S32).map_err(|_| invalid()),
        Type::U8 => u8::try_from(value).map(Val::U8).map_err(|_| invalid()),
        Type::U16 => u16::try_from(value).map(Val::U16).map_err(|_| invalid()),
        Type::U32 => u32::try_from(value).map(Val::U32).map_err(|_| invalid()),
        _ => Err(invalid()),
    }
}

pub(super) fn text<E: de::Error>(state: &mut State, ty: &Type, value: &str) -> Result<Val, E> {
    // These temporary text charges also apply when the resulting Val is numeric
    // or a char and does not retain the original string.
    state.text(value)?;
    match ty {
        Type::String => state.own(value).map(Val::String),
        Type::Char => {
            let mut chars = value.chars();
            let character = chars.next().ok_or_else(invalid)?;
            if chars.next().is_some() {
                return Err(invalid());
            }
            Ok(Val::Char(character))
        }
        Type::U64 if decode::decimal(value, false) => {
            value.parse().map(Val::U64).map_err(|_| invalid())
        }
        Type::S64 if decode::decimal(value, true) => {
            value.parse().map(Val::S64).map_err(|_| invalid())
        }
        Type::Float32 => decode::parse_float32(value)
            .map(Val::Float32)
            .map_err(|error| state.fail(error)),
        Type::Float64 => decode::parse_float64(value)
            .map(Val::Float64)
            .map_err(|error| state.fail(error)),
        Type::Enum(enumeration) if enumeration.names().any(|name| name == value) => {
            state.own(value).map(Val::Enum)
        }
        _ => Err(invalid()),
    }
}
