use super::{
    Arc, AtomicU64, LifecycleAuthorityHandle, LifecycleEligibility, PlatformError, ReleaseDigest,
    ReleaseUseEligibility, Row, WebUseEligibility,
};

impl ReleaseUseEligibility {
    pub(crate) fn from_web(
        owner: &LifecycleAuthorityHandle,
        projection: WebUseEligibility,
    ) -> Result<Self, PlatformError> {
        let authority = owner
            .required_authority()
            .ok_or_else(super::super::invalid)?;
        if !projection.belongs_to_authority(authority) || !projection.belongs_to_catalog(owner) {
            return Err(super::super::invalid());
        }
        let renderer = projection
            .layout()
            .manifest()
            .renderer
            .as_ref()
            .ok_or_else(crate::web::incompatible)?;
        let release = ReleaseDigest(renderer.digest.clone());
        crate::publication::validate_component(&release)?;
        let generation = projection.generation();
        let row = Arc::new(Row {
            publication: projection.publication().id.clone(),
            scope: projection.publication().scope.clone(),
            release,
            package: Some(projection.layout().package().clone()),
            allowed_generation: AtomicU64::new(generation),
        });
        let value = Self {
            lifecycle: LifecycleEligibility {
                owner: Arc::clone(&owner.owner),
                row,
                generation,
                projection: Some(Arc::new(projection)),
            },
            admission: None,
        };
        value.check_current()?;
        Ok(value)
    }
}
