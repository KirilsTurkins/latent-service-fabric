use serde::{Deserialize, Deserializer, Serializer};

#[expect(
    clippy::trivially_copy_pass_by_ref,
    reason = "Serde serialize_with callbacks receive a reference to the declared field type"
)]
pub(super) fn u64<S: Serializer>(value: &u64, serializer: S) -> Result<S::Ok, S::Error> {
    serializer.serialize_str(&value.to_string())
}

pub(super) fn deserialize_u64<'de, D: Deserializer<'de>>(deserializer: D) -> Result<u64, D::Error> {
    let value = String::deserialize(deserializer)?;
    canonical(&value)
        .ok_or_else(|| serde::de::Error::custom("expected canonical decimal u64 string"))
}

pub(super) fn deserialize_optional_u64<'de, D: Deserializer<'de>>(
    deserializer: D,
) -> Result<Option<u64>, D::Error> {
    Option::<String>::deserialize(deserializer)?
        .map(|value| {
            canonical(&value)
                .ok_or_else(|| serde::de::Error::custom("expected canonical decimal u64 string"))
        })
        .transpose()
}

fn canonical(value: &str) -> Option<u64> {
    if value.len() > 20 {
        return None;
    }
    value
        .parse::<u64>()
        .ok()
        .filter(|number| number.to_string() == value)
}

#[expect(
    clippy::ref_option,
    reason = "Serde serialize_with callbacks receive a reference to the declared Option field"
)]
pub(super) fn optional_u64<S: Serializer>(
    value: &Option<u64>,
    serializer: S,
) -> Result<S::Ok, S::Error> {
    match value {
        Some(value) => serializer.serialize_some(&value.to_string()),
        None => serializer.serialize_none(),
    }
}
