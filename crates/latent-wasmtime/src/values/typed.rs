//! Owned type-directed decoding after the unchanged whole-input preflight.
//!
//! There is no generic JSON tree on this path. A value-before-case variant may
//! temporarily borrow its raw payload, but parses it with the same ledger and
//! logical depth before returning. All strings and containers in the result own
//! their storage. The caller drops this decoder before running a rejection oracle.

mod records;
mod scalar;
mod sequences;
mod state;
mod tagged;
mod text;
mod variant;

use std::fmt;

use latent_core::PlatformError;
use serde::de::{self, DeserializeSeed, MapAccess, SeqAccess, Visitor};
use wasmtime::component::{Type, Val};

use super::{invalid_input, signature::node_bytes, ValueCodecLimits};
use state::State;

pub(super) fn params(
    types: &[Type],
    payload: &[u8],
    limits: ValueCodecLimits,
) -> Result<Vec<Val>, PlatformError> {
    let mut state = State::new(limits);
    let mut deserializer = serde_json::Deserializer::from_slice(payload);
    let result = sequences::Params {
        state: &mut state,
        types,
    }
    .deserialize(&mut deserializer)
    .and_then(|values| deserializer.end().map(|()| values));
    result.map_err(|_| state.failure.unwrap_or_else(invalid_input))
}

struct Seed<'a> {
    state: &'a mut State,
    ty: &'a Type,
    depth: usize,
    prepaid: bool,
}

impl<'de> DeserializeSeed<'de> for Seed<'_> {
    type Value = Val;

    fn deserialize<D: de::Deserializer<'de>>(self, deserializer: D) -> Result<Val, D::Error> {
        self.state.node(self.depth, self.prepaid)?;
        deserializer.deserialize_any(ValueVisitor {
            state: self.state,
            ty: self.ty,
            depth: self.depth,
        })
    }
}

struct ValueVisitor<'a> {
    state: &'a mut State,
    ty: &'a Type,
    depth: usize,
}

impl<'de> Visitor<'de> for ValueVisitor<'_> {
    type Value = Val;

    fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("a bounded value of the declared component type")
    }

    fn visit_bool<E: de::Error>(self, value: bool) -> Result<Val, E> {
        if matches!(self.ty, Type::Bool) {
            Ok(Val::Bool(value))
        } else {
            Err(invalid())
        }
    }

    fn visit_i64<E: de::Error>(self, value: i64) -> Result<Val, E> {
        scalar::signed(self.ty, value)
    }

    fn visit_u64<E: de::Error>(self, value: u64) -> Result<Val, E> {
        scalar::unsigned(self.ty, value)
    }

    fn visit_f64<E: de::Error>(self, value: f64) -> Result<Val, E> {
        // serde represents bare -0 as a negative floating zero. The unchanged
        // lexical preflight rejects all bare decimal/exponent spellings first.
        if value == 0.0 && value.is_sign_negative() {
            scalar::unsigned(self.ty, 0)
        } else {
            Err(invalid())
        }
    }

    fn visit_str<E: de::Error>(self, value: &str) -> Result<Val, E> {
        scalar::text(self.state, self.ty, value)
    }

    fn visit_seq<A: SeqAccess<'de>>(self, sequence: A) -> Result<Val, A::Error> {
        match self.ty {
            Type::List(list) => sequences::list(self.state, list, sequence, self.depth),
            Type::Tuple(tuple) => sequences::tuple(self.state, tuple, sequence, self.depth),
            Type::Flags(flags) => sequences::flags(self.state, flags, sequence),
            _ => Err(invalid()),
        }
    }

    fn visit_map<A: MapAccess<'de>>(self, object: A) -> Result<Val, A::Error> {
        match self.ty {
            Type::Record(record) => records::record(self.state, record, object, self.depth),
            Type::Variant(variant) => variant::variant(self.state, variant, object, self.depth),
            Type::Option(option) => tagged::option(self.state, option, object, self.depth),
            Type::Result(result) => tagged::result(self.state, result, object, self.depth),
            _ => Err(invalid()),
        }
    }
}

fn invalid<E: de::Error>() -> E {
    E::custom("invalid typed component value")
}

/// Checking for an extra item must not parse or allocate that item's value.
struct RejectExtra;

impl<'de> DeserializeSeed<'de> for RejectExtra {
    type Value = ();

    fn deserialize<D: de::Deserializer<'de>>(self, _: D) -> Result<(), D::Error> {
        Err(invalid())
    }
}
