use std::{borrow::Cow, fmt};

use serde::de::{self, DeserializeSeed, Visitor};

use super::State;

/// Fixed tag/field lookup borrows unescaped source text. Escaped text is copied
/// out of serde's reusable scratch; only a retained component name is charged.
pub(super) struct Text<'a> {
    pub(super) state: &'a mut State,
    pub(super) charged: bool,
}

impl<'de> DeserializeSeed<'de> for Text<'_> {
    type Value = Cow<'de, str>;

    fn deserialize<D: de::Deserializer<'de>>(
        self,
        deserializer: D,
    ) -> Result<Self::Value, D::Error> {
        deserializer.deserialize_str(self)
    }
}

impl<'de> Visitor<'de> for Text<'_> {
    type Value = Cow<'de, str>;

    fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("a bounded JSON string")
    }

    fn visit_borrowed_str<E: de::Error>(self, value: &'de str) -> Result<Self::Value, E> {
        if self.charged {
            self.state.text(value)?;
        }
        Ok(Cow::Borrowed(value))
    }

    fn visit_str<E: de::Error>(self, value: &str) -> Result<Self::Value, E> {
        if self.charged {
            self.state.text(value)?;
        }
        self.state.own(value).map(Cow::Owned)
    }
}

pub(super) fn own<E: de::Error>(state: &mut State, value: Cow<'_, str>) -> Result<String, E> {
    match value {
        Cow::Borrowed(value) => state.own(value),
        Cow::Owned(value) => Ok(value),
    }
}
