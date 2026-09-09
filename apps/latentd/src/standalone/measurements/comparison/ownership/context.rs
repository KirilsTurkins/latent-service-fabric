use latent_core::{Metadata, PlatformErrorCode};
use latent_wasmtime::{InvocationContextCharge, WasmtimeBackend};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

use super::{
    request::{self, Control, Template},
    Result,
};

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Context {
    pub schema: String,
    pub shape: String,
    pub claims: Metadata,
    pub baggage: Metadata,
    pub metadata: Metadata,
}

impl Context {
    pub fn small() -> Self {
        Self {
            schema: "latent.optimization.ownership-context.v1".into(),
            shape: "context-small".into(),
            claims: Metadata::from([
                ("role".into(), "reader".into()),
                ("private.claim".into(), "hidden".into()),
            ]),
            baggage: Metadata::from([
                ("locale".into(), "en".into()),
                ("private.baggage".into(), "hidden".into()),
            ]),
            metadata: Metadata::from([
                ("guest.visible".into(), request::identifier(0).0),
                ("internal.context".into(), "hidden".into()),
            ]),
        }
    }
    pub fn content_bytes(&self) -> usize {
        [&self.claims, &self.baggage, &self.metadata]
            .iter()
            .flat_map(|m| m.iter())
            .map(|(k, v)| k.len() + v.len())
            .sum()
    }
    fn sized(shape: &str, total: usize) -> Result<Self> {
        let mut value = Self::small();
        value.shape = shape.into();
        for (map, key) in [
            (&mut value.claims, "private.claim"),
            (&mut value.baggage, "private.baggage"),
            (&mut value.metadata, "internal.context"),
        ] {
            map.insert(key.into(), String::new());
        }
        let extra = total
            .checked_sub(value.content_bytes())
            .ok_or("context fixture content bound")?;
        let third = extra / 3;
        value
            .claims
            .insert("private.claim".into(), "c".repeat(third));
        value
            .baggage
            .insert("private.baggage".into(), "b".repeat(third));
        value
            .metadata
            .insert("internal.context".into(), "m".repeat(extra - 2 * third));
        Ok(value)
    }
    pub fn validate(&self, shape: &str) -> Result<()> {
        if self.schema != "latent.optimization.ownership-context.v1"
            || self.shape != shape
            || self.claims.len() != 2
            || self.baggage.len() != 2
            || self.metadata.len() != 2
            || self.claims.get("role").map(String::as_str) != Some("reader")
            || self.baggage.get("locale").map(String::as_str) != Some("en")
            || self.metadata.get("guest.visible") != Some(&request::identifier(0).0)
            || !self.claims.contains_key("private.claim")
            || !self.baggage.contains_key("private.baggage")
            || !self.metadata.contains_key("internal.context")
        {
            return Err("ownership context fixture shape".into());
        }
        if shape == "context-small" && self.content_bytes() != Self::small().content_bytes()
            || shape == "context-64k" && self.content_bytes() != 65_536
        {
            return Err("ownership context fixture size".into());
        }
        Ok(())
    }
}

pub(super) fn charge(value: InvocationContextCharge) -> Value {
    json!({"maximum_bytes":value.maximum_bytes.to_string(),"charged_bytes":value.charged_bytes.to_string(),
        "remaining_bytes":value.remaining_bytes.to_string()})
}

type ChargedContexts = Vec<(Context, Value)>;
type GenerationResult = (ChargedContexts, Vec<Value>);

pub(super) fn generate(backend: &WasmtimeBackend, template: &Template) -> Result<GenerationResult> {
    let control = Control::new(request::identifier(0))?;
    let mut checks = Vec::new();
    let mut values = Vec::new();
    let mut probe = |context: &Context| -> Result<Option<InvocationContextCharge>> {
        if checks.len() >= 20 {
            return Err("context fixture sizing probe limit".into());
        }
        let request = request::build(template, context, b"[]", &control, "snapshot");
        match backend.invocation_context_charge(&request) {
            Ok(value) => {
                checks.push(json!({"shape":context.shape,"content_bytes":context.content_bytes().to_string(),
                "charge":charge(value),"error":null}));
                Ok(Some(value))
            }
            Err(error) if error.code == PlatformErrorCode::ResourceExhausted => {
                checks.push(json!({"shape":context.shape,"content_bytes":context.content_bytes().to_string(),
                    "charge":null,"error":"resource-exhausted"}));
                Ok(None)
            }
            Err(error) => Err(super::platform(error)),
        }
    };
    for context in [Context::small(), Context::sized("context-64k", 65_536)?] {
        let observed = probe(&context)?.ok_or("bounded context fixture rejected")?;
        values.push((context, charge(observed)));
    }
    let mut low = 65_536;
    let mut high = 1_048_576;
    loop {
        if low > high {
            return Err("context fixture headroom unavailable".into());
        }
        let middle = low + (high - low) / 2;
        let context = Context::sized("context-near-limit", middle)?;
        match probe(&context)? {
            Some(value) if (512..=1024).contains(&value.remaining_bytes) => {
                values.push((context, charge(value)));
                break;
            }
            Some(value) if value.remaining_bytes > 1024 => low = middle + 1,
            _ => {
                high = middle
                    .checked_sub(1)
                    .ok_or("context fixture search underflow")?;
            }
        }
    }
    Ok((values, checks))
}
