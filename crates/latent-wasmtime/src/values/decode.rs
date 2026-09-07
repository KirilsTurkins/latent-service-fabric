use latent_core::PlatformError;
use serde_json::Value;
use wasmtime::component::{Type, Val};

use super::{charge, invalid_input, limit, signature::node_bytes, unsupported, ValueCodecLimits};

pub(super) fn params(
    types: &[Type],
    value: Value,
    limits: ValueCodecLimits,
) -> Result<Vec<Val>, PlatformError> {
    let Value::Array(values) = value else {
        return Err(invalid_input());
    };
    if values.len() != types.len() {
        return Err(invalid_input());
    }
    let mut state = Decoder {
        remaining: limits.max_decoded_value_bytes,
        limits,
    };
    charge(&mut state.remaining, node_bytes())?;
    types
        .iter()
        .zip(values)
        .map(|(ty, value)| state.value(ty, value, 1))
        .collect()
}

struct Decoder {
    remaining: usize,
    limits: ValueCodecLimits,
}

impl Decoder {
    fn text(&mut self, value: Value) -> Result<String, PlatformError> {
        let Value::String(text) = value else {
            return Err(invalid_input());
        };
        if text.len() > self.limits.max_string_bytes {
            return Err(limit());
        }
        charge(
            &mut self.remaining,
            text.len().checked_mul(2).ok_or_else(limit)?,
        )?;
        Ok(text)
    }

    fn value(&mut self, ty: &Type, value: Value, depth: usize) -> Result<Val, PlatformError> {
        if depth > self.limits.max_depth {
            return Err(limit());
        }
        charge(&mut self.remaining, node_bytes())?;
        match ty {
            Type::List(list) => self.list(list, value, depth),
            Type::Tuple(tuple) => self.tuple(tuple, value, depth),
            Type::Record(record) => self.record(record, value, depth),
            Type::Variant(variant) => self.variant(variant, value, depth),
            Type::Enum(enumeration) => {
                let name = self.text(value)?;
                if !enumeration.names().any(|candidate| candidate == name) {
                    return Err(invalid_input());
                }
                Ok(Val::Enum(name))
            }
            Type::Flags(flags) => self.flags(flags, value),
            Type::Option(option) => self.option(option, value, depth),
            Type::Result(result) => self.result(result, value, depth),
            _ => self.scalar(ty, value),
        }
    }

    fn scalar(&mut self, ty: &Type, value: Value) -> Result<Val, PlatformError> {
        macro_rules! unsigned {
            ($variant:ident, $target:ty) => {
                Val::$variant(
                    <$target>::try_from(value.as_u64().ok_or_else(invalid_input)?)
                        .map_err(|_| invalid_input())?,
                )
            };
        }
        macro_rules! signed {
            ($variant:ident, $target:ty) => {
                Val::$variant(
                    <$target>::try_from(value.as_i64().ok_or_else(invalid_input)?)
                        .map_err(|_| invalid_input())?,
                )
            };
        }
        Ok(match ty {
            Type::Bool => Val::Bool(value.as_bool().ok_or_else(invalid_input)?),
            Type::U8 => unsigned!(U8, u8),
            Type::U16 => unsigned!(U16, u16),
            Type::U32 => unsigned!(U32, u32),
            Type::S8 => signed!(S8, i8),
            Type::S16 => signed!(S16, i16),
            Type::S32 => signed!(S32, i32),
            Type::U64 => {
                let text = self.text(value)?;
                if !decimal(&text, false) {
                    return Err(invalid_input());
                }
                Val::U64(text.parse().map_err(|_| invalid_input())?)
            }
            Type::S64 => {
                let text = self.text(value)?;
                if !decimal(&text, true) {
                    return Err(invalid_input());
                }
                Val::S64(text.parse().map_err(|_| invalid_input())?)
            }
            Type::Float32 => Val::Float32(parse_float32(&self.text(value)?)?),
            Type::Float64 => Val::Float64(parse_float64(&self.text(value)?)?),
            Type::Char => {
                let text = self.text(value)?;
                let mut chars = text.chars();
                let scalar = chars.next().ok_or_else(invalid_input)?;
                if chars.next().is_some() {
                    return Err(invalid_input());
                }
                Val::Char(scalar)
            }
            Type::String => Val::String(self.text(value)?),
            _ => return Err(unsupported()),
        })
    }

    fn list(
        &mut self,
        list: &wasmtime::component::types::List,
        value: Value,
        depth: usize,
    ) -> Result<Val, PlatformError> {
        Ok({
            let values = array(value, self.limits)?;
            Val::List(
                values
                    .into_iter()
                    .map(|child| self.value(&list.ty(), child, depth + 1))
                    .collect::<Result<_, _>>()?,
            )
        })
    }

    fn tuple(
        &mut self,
        tuple: &wasmtime::component::types::Tuple,
        value: Value,
        depth: usize,
    ) -> Result<Val, PlatformError> {
        Ok({
            let values = array(value, self.limits)?;
            if values.len() != tuple.types().len() {
                return Err(invalid_input());
            }
            Val::Tuple(
                tuple
                    .types()
                    .zip(values)
                    .map(|(ty, child)| self.value(&ty, child, depth + 1))
                    .collect::<Result<_, _>>()?,
            )
        })
    }

    fn record(
        &mut self,
        record: &wasmtime::component::types::Record,
        value: Value,
        depth: usize,
    ) -> Result<Val, PlatformError> {
        Ok({
            let Value::Object(mut fields) = value else {
                return Err(invalid_input());
            };
            if fields.len() != record.fields().len() {
                return Err(invalid_input());
            }
            let mut output = Vec::new();
            for field in record.fields() {
                let child = fields.remove(field.name).ok_or_else(invalid_input)?;
                charge(
                    &mut self.remaining,
                    field.name.len().checked_mul(2).ok_or_else(limit)?,
                )?;
                let child = self.value(&field.ty, child, depth + 1)?;
                output.push((field.name.to_owned(), child));
            }
            Val::Record(output)
        })
    }

    fn variant(
        &mut self,
        variant: &wasmtime::component::types::Variant,
        value: Value,
        depth: usize,
    ) -> Result<Val, PlatformError> {
        Ok({
            let Value::Object(mut object) = value else {
                return Err(invalid_input());
            };
            let name = self.text(object.remove("case").ok_or_else(invalid_input)?)?;
            let case = variant
                .cases()
                .find(|case| case.name == name)
                .ok_or_else(invalid_input)?;
            let child = match case.ty {
                Some(ty) => Some(Box::new(self.value(
                    &ty,
                    object.remove("value").ok_or_else(invalid_input)?,
                    depth + 1,
                )?)),
                None => None,
            };
            if !object.is_empty() {
                return Err(invalid_input());
            }
            Val::Variant(name, child)
        })
    }

    fn flags(
        &mut self,
        flags: &wasmtime::component::types::Flags,
        value: Value,
    ) -> Result<Val, PlatformError> {
        Ok({
            let values = array(value, self.limits)?;
            let mut names = std::collections::BTreeSet::new();
            for value in values {
                let name = self.text(value)?;
                charge(&mut self.remaining, node_bytes())?;
                if !flags.names().any(|candidate| candidate == name) || !names.insert(name) {
                    return Err(invalid_input());
                }
            }
            Val::Flags(flags.names().filter_map(|name| names.take(name)).collect())
        })
    }

    fn option(
        &mut self,
        option: &wasmtime::component::types::OptionType,
        value: Value,
        depth: usize,
    ) -> Result<Val, PlatformError> {
        Ok({
            let (tag, value) = tag(value)?;
            match tag.as_str() {
                "none" if value.is_null() => Val::Option(None),
                "some" => Val::Option(Some(Box::new(self.value(
                    &option.ty(),
                    value,
                    depth + 1,
                )?))),
                _ => return Err(invalid_input()),
            }
        })
    }

    fn result(
        &mut self,
        result: &wasmtime::component::types::ResultType,
        value: Value,
        depth: usize,
    ) -> Result<Val, PlatformError> {
        Ok({
            let (tag, value) = tag(value)?;
            match tag.as_str() {
                "ok" => Val::Result(Ok(self.branch(result.ok(), value, depth + 1)?)),
                "err" => Val::Result(Err(self.branch(result.err(), value, depth + 1)?)),
                _ => return Err(invalid_input()),
            }
        })
    }

    fn branch(
        &mut self,
        ty: Option<Type>,
        value: Value,
        depth: usize,
    ) -> Result<Option<Box<Val>>, PlatformError> {
        match ty {
            Some(ty) => Ok(Some(Box::new(self.value(&ty, value, depth)?))),
            None if value.is_null() => Ok(None),
            None => Err(invalid_input()),
        }
    }
}

fn array(value: Value, limits: ValueCodecLimits) -> Result<Vec<Value>, PlatformError> {
    let Value::Array(values) = value else {
        return Err(invalid_input());
    };
    if values.len() > limits.max_collection_items {
        return Err(limit());
    }
    Ok(values)
}

fn tag(value: Value) -> Result<(String, Value), PlatformError> {
    let Value::Object(object) = value else {
        return Err(invalid_input());
    };
    if object.len() != 1 {
        return Err(invalid_input());
    }
    object.into_iter().next().ok_or_else(invalid_input)
}

fn decimal(value: &str, signed: bool) -> bool {
    let magnitude = if signed {
        value.strip_prefix('-').unwrap_or(value)
    } else {
        value
    };
    (magnitude == "0" && value == "0")
        || (matches!(magnitude.as_bytes().first(), Some(b'1'..=b'9'))
            && magnitude.bytes().all(|byte| byte.is_ascii_digit()))
}

fn finite_decimal(value: &str) -> bool {
    let bytes = value.as_bytes();
    let mut index = usize::from(bytes.first() == Some(&b'-'));
    match bytes.get(index) {
        Some(b'0') => index += 1,
        Some(b'1'..=b'9') => {
            index += 1;
            while bytes.get(index).is_some_and(u8::is_ascii_digit) {
                index += 1;
            }
        }
        _ => return false,
    }
    if bytes.get(index) == Some(&b'.') {
        index += 1;
        let start = index;
        while bytes.get(index).is_some_and(u8::is_ascii_digit) {
            index += 1;
        }
        if index == start {
            return false;
        }
    }
    if matches!(bytes.get(index), Some(b'e' | b'E')) {
        index += 1;
        if matches!(bytes.get(index), Some(b'+' | b'-')) {
            index += 1;
        }
        let start = index;
        while bytes.get(index).is_some_and(u8::is_ascii_digit) {
            index += 1;
        }
        if index == start {
            return false;
        }
    }
    index == bytes.len()
}

fn parse_float32(value: &str) -> Result<f32, PlatformError> {
    match value {
        "nan" => Ok(f32::NAN),
        "inf" => Ok(f32::INFINITY),
        "-inf" => Ok(f32::NEG_INFINITY),
        value if finite_decimal(value) => value
            .parse::<f32>()
            .ok()
            .filter(|value| value.is_finite())
            .ok_or_else(invalid_input),
        _ => Err(invalid_input()),
    }
}

fn parse_float64(value: &str) -> Result<f64, PlatformError> {
    match value {
        "nan" => Ok(f64::NAN),
        "inf" => Ok(f64::INFINITY),
        "-inf" => Ok(f64::NEG_INFINITY),
        value if finite_decimal(value) => value
            .parse::<f64>()
            .ok()
            .filter(|value| value.is_finite())
            .ok_or_else(invalid_input),
        _ => Err(invalid_input()),
    }
}
