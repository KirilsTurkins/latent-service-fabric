//! Borrowed serialization in the existing Value object's sorted key order.

use latent_manifest::__serde::{
    ser::{SerializeSeq, SerializeStruct},
    Serialize, Serializer,
};

use super::super::compiler::{CompiledCatalog, RouteView};

pub(super) struct Snapshot<'a>(pub &'a CompiledCatalog);

impl Serialize for Snapshot<'_> {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        let mut state = serializer.serialize_struct("Snapshot", 5)?;
        state.serialize_field("bindings", &[] as &[()])?;
        state.serialize_field("generated_at_unix_millis", &self.0.generated_at_unix_millis)?;
        state.serialize_field("generation", &self.0.generation.0)?;
        state.serialize_field("policy_digests", &[] as &[()])?;
        state.serialize_field("services", &Services(self.0))?;
        state.end()
    }
}

struct Services<'a>(&'a CompiledCatalog);
impl Serialize for Services<'_> {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        let routes = self.0.route_views();
        let mut state = serializer.serialize_seq(Some(routes.len()))?;
        for route in routes {
            state.serialize_element(&Service(route))?;
        }
        state.end()
    }
}

struct Service<'a>(RouteView<'a>);
impl Serialize for Service<'_> {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        let mut state = serializer.serialize_struct("Service", 4)?;
        state.serialize_field("revisions", &Revisions(&self.0))?;
        state.serialize_field("route", self.0.id())?;
        state.serialize_field("service", &self.0.service().0)?;
        state.serialize_field("tenant", &self.0.tenant().0)?;
        state.end()
    }
}

struct Revisions<'view, 'catalog>(&'view RouteView<'catalog>);
impl Serialize for Revisions<'_, '_> {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        let revisions = self.0.revisions();
        let mut state = serializer.serialize_seq(Some(revisions.len()))?;
        for revision in revisions {
            state.serialize_element(&Revision(revision))?;
        }
        state.end()
    }
}

struct Revision<'a>(&'a super::super::compiler::RevisionRecord);
impl Serialize for Revision<'_> {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        let mut state = serializer.serialize_struct("Revision", 4)?;
        state.serialize_field("attributes", &self.0.attributes)?;
        state.serialize_field("release", &self.0.deployment.release.0)?;
        state.serialize_field("revision", &self.0.revision.0)?;
        state.serialize_field("weight", &self.0.deployment.route_weight)?;
        state.end()
    }
}
