use serde::{Deserialize, Deserializer};

pub(super) fn present<'de, D: Deserializer<'de>>(
    deserializer: D,
) -> Result<Option<latent_manifest::RendererProfile>, D::Error> {
    let profile = latent_manifest::RendererProfile::deserialize(deserializer)?;
    if profile != latent_manifest::RendererProfile::AngularSsrComponentV1 {
        return Err(serde::de::Error::custom(
            "unsupported node renderer profile",
        ));
    }
    Ok(Some(profile))
}
