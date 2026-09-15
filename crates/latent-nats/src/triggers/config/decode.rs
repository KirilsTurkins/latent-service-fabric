//! Bound configuration collection allocation while decoding, before validation.
use super::TriggerBinding;
use serde::{
    de::{Error, SeqAccess, Visitor},
    Deserialize, Deserializer,
};
use std::{fmt, marker::PhantomData};

fn limited<'de, T: Deserialize<'de>, D: Deserializer<'de>, const N: usize>(
    d: D,
) -> Result<Vec<T>, D::Error> {
    struct Items<T, const N: usize>(PhantomData<T>);
    impl<'de, T: Deserialize<'de>, const N: usize> Visitor<'de> for Items<T, N> {
        type Value = Vec<T>;
        fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
            f.write_str("a bounded configuration array")
        }
        fn visit_seq<A: SeqAccess<'de>>(self, mut a: A) -> Result<Vec<T>, A::Error> {
            let mut items = Vec::new();
            while let Some(item) = a.next_element()? {
                if items.len() == N {
                    return Err(A::Error::custom("configuration array exceeds its bound"));
                }
                items.push(item);
            }
            Ok(items)
        }
    }
    d.deserialize_seq(Items::<T, N>(PhantomData))
}
pub(super) fn bindings<'de, D: Deserializer<'de>>(d: D) -> Result<Vec<TriggerBinding>, D::Error> {
    limited::<_, _, 256>(d)
}
fn root_bytes<'de, D: Deserializer<'de>>(d: D) -> Result<Vec<u8>, D::Error> {
    limited::<_, _, 16384>(d)
}
pub(super) fn roots<'de, D: Deserializer<'de>>(d: D) -> Result<Vec<Vec<u8>>, D::Error> {
    #[derive(Deserialize)]
    struct Root(#[serde(deserialize_with = "root_bytes")] Vec<u8>);
    let roots = limited::<Root, _, 8>(d)?;
    Ok(roots.into_iter().map(|r| r.0).collect())
}
