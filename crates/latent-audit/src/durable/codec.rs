use super::{
    corrupt, invalid,
    model::{
        AuditActorIdentity, AuditControlAction, AuditIdentities, AuditObservation,
        AuditOperationAttempt, AuditOperationConclusion, AuditOperationResult, AuditRecordData,
        AuditScope, AuditStoredRecord,
    },
    Result,
};
use latent_core::{ArtifactBlobDigest, PackageDigest, ReleaseDigest, RevisionId, RouteGeneration};
use serde::{
    de::{DeserializeOwned, DeserializeSeed, MapAccess, SeqAccess, Visitor},
    Deserialize, Serialize,
};
use sha2::{Digest, Sha256};
use std::{fmt, io::Write};

pub(super) trait WireText: Sized {
    fn text(&self) -> &str;
    fn parse(s: String) -> std::result::Result<Self, ()>;
}
impl WireText for ArtifactBlobDigest {
    fn text(&self) -> &str {
        self.as_str()
    }
    fn parse(s: String) -> std::result::Result<Self, ()> {
        s.try_into().map_err(|_| ())
    }
}
impl WireText for PackageDigest {
    fn text(&self) -> &str {
        self.as_str()
    }
    fn parse(s: String) -> std::result::Result<Self, ()> {
        s.try_into().map_err(|_| ())
    }
}
impl WireText for ReleaseDigest {
    fn text(&self) -> &str {
        &self.0
    }
    fn parse(s: String) -> std::result::Result<Self, ()> {
        s.parse::<ArtifactBlobDigest>().map_err(|_| ())?;
        Ok(Self(s))
    }
}
impl WireText for RevisionId {
    fn text(&self) -> &str {
        &self.0
    }
    fn parse(s: String) -> std::result::Result<Self, ()> {
        token(&s, 256).map_err(|_| ())?;
        Ok(Self(s))
    }
}
impl WireText for latent_core::DeploymentId {
    fn text(&self) -> &str {
        &self.0
    }
    fn parse(s: String) -> std::result::Result<Self, ()> {
        token(&s, 256).map_err(|_| ())?;
        Ok(Self(s))
    }
}
pub(super) mod text {
    use super::{Deserialize, WireText};
    pub fn serialize<S: serde::Serializer, T: WireText>(
        v: &T,
        s: S,
    ) -> std::result::Result<S::Ok, S::Error> {
        s.serialize_str(v.text())
    }
    pub fn deserialize<'de, D: serde::Deserializer<'de>, T: WireText>(
        d: D,
    ) -> std::result::Result<T, D::Error> {
        T::parse(String::deserialize(d)?)
            .map_err(|()| serde::de::Error::custom("invalid audit identity"))
    }
}
pub(super) mod optional {
    use super::{text, Serialize, WireText};
    #[expect(
        clippy::ref_option,
        reason = "Serde field serializers receive a reference to the complete Option"
    )]
    pub fn serialize<S: serde::Serializer, T: WireText>(
        v: &Option<T>,
        s: S,
    ) -> std::result::Result<S::Ok, S::Error> {
        v.as_ref().map(WireText::text).serialize(s)
    }
    pub fn deserialize<'de, D: serde::Deserializer<'de>, T: WireText>(
        d: D,
    ) -> std::result::Result<Option<T>, D::Error> {
        text::deserialize(d).map(Some)
    }
}
pub(super) mod generation {
    use super::{Deserialize, RouteGeneration, Serialize};
    #[expect(
        clippy::ref_option,
        reason = "Serde field serializers receive a reference to the complete Option"
    )]
    pub fn serialize<S: serde::Serializer>(
        v: &Option<RouteGeneration>,
        s: S,
    ) -> std::result::Result<S::Ok, S::Error> {
        v.map(|g| g.0).serialize(s)
    }
    pub fn deserialize<'de, D: serde::Deserializer<'de>>(
        d: D,
    ) -> std::result::Result<Option<RouteGeneration>, D::Error> {
        u64::deserialize(d).map(|n| Some(RouteGeneration(n)))
    }
}
pub(super) fn present<'de, D: serde::Deserializer<'de>, T: Deserialize<'de>>(
    d: D,
) -> std::result::Result<Option<T>, D::Error> {
    T::deserialize(d).map(Some)
}
pub(super) fn token(v: &str, max: usize) -> Result<()> {
    if v.is_empty() || v.len() > max || v.chars().any(char::is_control) || v.trim() != v {
        Err(invalid())
    } else {
        Ok(())
    }
}
pub(super) fn scope(v: &AuditScope) -> Result<()> {
    if let AuditScope::Tenant(t) = v {
        token(&t.0, 512)?;
    }
    Ok(())
}
pub(super) fn actor(v: &AuditActorIdentity) -> Result<()> {
    token(&v.subject, 512)
}
pub(super) fn identities(v: &AuditIdentities) -> Result<()> {
    if v.policies.len() > 8 {
        return Err(invalid());
    }
    if let Some(c) = &v.component {
        c.0.parse::<ArtifactBlobDigest>().map_err(|_| invalid())?;
    }
    if let Some(r) = &v.revision {
        token(&r.0, 256)?;
    }
    if let Some(r) = &v.deployment {
        token(&r.0, 256)?;
    }
    if let Some(r) = &v.rollout {
        token(r, 256)?;
    }
    for (i, p) in v.policies.iter().enumerate() {
        token(&p.scope, 128)?;
        if p.generation == 0
            || v.policies[..i]
                .iter()
                .any(|o| o.role == p.role && o.scope == p.scope)
        {
            return Err(invalid());
        }
    }
    Ok(())
}
pub(super) fn attempt(v: &AuditOperationAttempt) -> Result<()> {
    scope(&v.scope)?;
    actor(&v.actor)?;
    token(&v.operation_id, 128)?;
    if matches!(
        v.action,
        AuditControlAction::Publish
            | AuditControlAction::Revoke
            | AuditControlAction::Retire
            | AuditControlAction::RenewEvidence
    ) && v.preview_receipt_digest.is_none()
    {
        return Err(invalid());
    }
    identities(&v.identities)
}
pub(super) fn conclusion(v: &AuditOperationConclusion) -> Result<()> {
    identities(&v.identities)?;
    if matches!(
        v.result,
        AuditOperationResult::NotStarted | AuditOperationResult::Unknown
    ) && v.receipt_digest.is_some()
    {
        return Err(invalid());
    }
    Ok(())
}
pub(super) fn observation(v: &AuditObservation) -> Result<()> {
    use crate::{AuditOutcome as O, Phase2AuditEventKind as K};
    scope(&v.scope)?;
    actor(&v.actor)?;
    identities(&v.identities)?;
    let cache = matches!(v.kind, K::CacheHit | K::CacheMiss | K::CacheCorruption);
    if cache != v.cache_kind.is_some() {
        return Err(invalid());
    }
    let denied = matches!(
        v.kind,
        K::VerificationRejected | K::PromotionRejected | K::RollbackRejected
    );
    if denied && v.outcome == O::Succeeded {
        return Err(invalid());
    }
    if matches!(
        v.kind,
        K::VerificationAccepted
            | K::ReleaseRevoked
            | K::ReleaseRetired
            | K::PromotionAccepted
            | K::RollbackAccepted
    ) && v.outcome != O::Succeeded
    {
        return Err(invalid());
    }
    if matches!(
        v.kind,
        K::VerificationAccepted | K::ReleaseRevoked | K::ReleaseRetired
    ) && v.identities.component.is_none()
    {
        return Err(invalid());
    }
    Ok(())
}
pub(super) fn record(v: &AuditStoredRecord) -> Result<()> {
    if v.format_version != 1
        || v.sequence == 0
        || !hex(&v.epoch, 32)
        || !hex(&v.previous_digest, 64)
    {
        return Err(corrupt());
    }
    scope(&v.scope)?;
    actor(&v.actor)?;
    match &v.data {
        AuditRecordData::Observation(o) => {
            observation(o)?;
            if o.scope != v.scope || o.actor != v.actor {
                return Err(corrupt());
            }
        }
        AuditRecordData::Attempt(a) => {
            attempt(a)?;
            if a.scope != v.scope || a.actor != v.actor {
                return Err(corrupt());
            }
        }
        AuditRecordData::Outcome {
            attempt_sequence,
            conclusion: c,
        } => {
            if *attempt_sequence == 0 || *attempt_sequence >= v.sequence {
                return Err(corrupt());
            }
            conclusion(c)?;
        }
    }
    Ok(())
}
pub(super) fn hex(v: &str, n: usize) -> bool {
    v.len() == n
        && v.bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}
pub(super) fn envelope(
    scope: &AuditScope,
    actor: &AuditActorIdentity,
    data: AuditRecordData,
    maximum: usize,
) -> Result<()> {
    let value = AuditStoredRecord {
        format_version: 1,
        epoch: "f".repeat(32),
        sequence: u64::MAX,
        previous_digest: "f".repeat(64),
        accepted_at_unix_millis: u64::MAX,
        scope: scope.clone(),
        actor: actor.clone(),
        data,
    };
    encode(&value, maximum).map(|_| ())
}
pub(super) fn digest(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}
pub(super) fn blob(bytes: &[u8]) -> ArtifactBlobDigest {
    format!("sha256:{}", digest(bytes))
        .parse()
        .expect("hash is canonical")
}
struct Limited {
    bytes: Vec<u8>,
    maximum: usize,
}
impl Write for Limited {
    fn write(&mut self, bytes: &[u8]) -> std::io::Result<usize> {
        if bytes.len() > self.maximum - self.bytes.len() {
            return Err(std::io::ErrorKind::FileTooLarge.into());
        }
        self.bytes.extend_from_slice(bytes);
        Ok(bytes.len())
    }
    fn flush(&mut self) -> std::io::Result<()> {
        Ok(())
    }
}
pub(super) fn encode<T: Serialize>(v: &T, maximum: usize) -> Result<Vec<u8>> {
    let mut output = Limited {
        bytes: Vec::with_capacity(maximum),
        maximum,
    };
    serde_json::to_writer(&mut output, v).map_err(|_| invalid())?;
    Ok(output.bytes)
}
pub(super) fn decode<T: DeserializeOwned>(bytes: &[u8], maximum: usize) -> Result<T> {
    if bytes.len() > maximum {
        return Err(corrupt());
    }
    let mut nodes = 256;
    let mut d = serde_json::Deserializer::from_slice(bytes);
    Scan {
        depth: 0,
        nodes: &mut nodes,
    }
    .deserialize(&mut d)
    .map_err(|_| corrupt())?;
    d.end().map_err(|_| corrupt())?;
    serde_json::from_slice(bytes).map_err(|_| corrupt())
}
pub(super) fn normalize<T: Serialize + DeserializeOwned>(v: &T, maximum: usize) -> Result<T> {
    decode(&encode(v, maximum)?, maximum)
}
struct Scan<'a> {
    depth: usize,
    nodes: &'a mut usize,
}
impl<'de> DeserializeSeed<'de> for Scan<'_> {
    type Value = ();
    fn deserialize<D: serde::Deserializer<'de>>(self, d: D) -> std::result::Result<(), D::Error> {
        if self.depth > 8 || *self.nodes == 0 {
            return Err(serde::de::Error::custom("audit json limit"));
        }
        *self.nodes -= 1;
        d.deserialize_any(self)
    }
}
impl<'de> Visitor<'de> for Scan<'_> {
    type Value = ();
    fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("bounded audit JSON")
    }
    fn visit_bool<E: serde::de::Error>(self, _: bool) -> std::result::Result<(), E> {
        Ok(())
    }
    fn visit_u64<E: serde::de::Error>(self, _: u64) -> std::result::Result<(), E> {
        Ok(())
    }
    fn visit_i64<E: serde::de::Error>(self, _: i64) -> std::result::Result<(), E> {
        Ok(())
    }
    fn visit_str<E: serde::de::Error>(self, s: &str) -> std::result::Result<(), E> {
        if s.len() > 512 {
            Err(E::custom("audit string limit"))
        } else {
            Ok(())
        }
    }
    fn visit_seq<A: SeqAccess<'de>>(self, mut a: A) -> std::result::Result<(), A::Error> {
        let mut count = 0;
        while a
            .next_element_seed(Scan {
                depth: self.depth + 1,
                nodes: self.nodes,
            })?
            .is_some()
        {
            count += 1;
            if count > 8 {
                return Err(serde::de::Error::custom("audit array limit"));
            }
        }
        Ok(())
    }
    fn visit_map<A: MapAccess<'de>>(self, mut a: A) -> std::result::Result<(), A::Error> {
        while a
            .next_key_seed(Scan {
                depth: self.depth + 1,
                nodes: self.nodes,
            })?
            .is_some()
        {
            a.next_value_seed(Scan {
                depth: self.depth + 1,
                nodes: self.nodes,
            })?;
        }
        Ok(())
    }
}
