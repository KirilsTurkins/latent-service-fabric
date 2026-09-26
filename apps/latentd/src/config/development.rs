//! Explicit guest-only test inputs; the node's authority clock is unchanged.

use latent_core::PlatformError;
use latent_wasmtime::{DevelopmentClockReadings, ExecutionIsolationProfile};
use serde::{de, Deserialize, Deserializer};

use super::{invalid, NodeConfig};

#[derive(Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct DevelopmentTestConfig {
    format_version: u32,
    consent: bool,
    purpose: String,
    #[serde(deserialize_with = "object")]
    guest_clock: GuestClock,
}

pub(super) fn present<'de, D: Deserializer<'de>>(
    input: D,
) -> Result<Option<DevelopmentTestConfig>, D::Error> {
    object(input).map(Some)
}

fn object<'de, T: Deserialize<'de>, D: Deserializer<'de>>(input: D) -> Result<T, D::Error> {
    struct Object<T>(std::marker::PhantomData<T>);
    impl<'de, T: Deserialize<'de>> de::Visitor<'de> for Object<T> {
        type Value = T;

        fn expecting(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
            formatter.write_str("a development fixture object")
        }

        fn visit_map<M: de::MapAccess<'de>>(self, map: M) -> Result<T, M::Error> {
            T::deserialize(de::value::MapAccessDeserializer::new(map))
        }
    }
    input.deserialize_map(Object(std::marker::PhantomData))
}

#[derive(Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct GuestClock {
    monotonic_nanos: String,
    wall_unix_millis: String,
}

impl DevelopmentTestConfig {
    pub(super) fn clock_readings(
        &self,
        node: &NodeConfig,
    ) -> Result<DevelopmentClockReadings, PlatformError> {
        if self.format_version != 1
            || !self.consent
            || self.purpose != "disposable-development-tests"
            || node.security_profile != ExecutionIsolationProfile::LocalExperimental
            || node.isolated_aot.is_some()
            || node.renderer_profile.is_some()
            || node.http_ingress.is_some()
        {
            return Err(invalid("developmentTest.explicitLocalTestRequired"));
        }
        Ok(DevelopmentClockReadings {
            monotonic_nanos: reading(&self.guest_clock.monotonic_nanos)?,
            wall_unix_millis: reading(&self.guest_clock.wall_unix_millis)?,
        })
    }
}

fn reading(value: &str) -> Result<u64, PlatformError> {
    if value.is_empty()
        || value.len() > 20
        || !value.bytes().all(|byte| byte.is_ascii_digit())
        || (value.len() > 1 && value.starts_with('0'))
    {
        return Err(invalid("developmentTest.guestClock"));
    }
    value
        .parse()
        .map_err(|_| invalid("developmentTest.guestClock"))
}
