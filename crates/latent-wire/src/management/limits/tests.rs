use super::*;

fn small_response(max_response_bytes: usize) -> ManagementLimits {
    ManagementLimits {
        max_response_bytes,
        max_metadata_entries: 1,
        max_metadata_bytes: 1,
        max_string_bytes: 1,
        max_id_bytes: 1,
        max_page_token_bytes: 1,
        max_collection_entries: 1,
        max_route_services: 1,
        max_route_revisions: 1,
        ..ManagementLimits::default()
    }
}

#[test]
fn response_floor_agrees_with_the_scoped_route_source() {
    // Every other envelope-dependent ceiling fits even the rejected envelope.
    // The boundary therefore detects the route header floor specifically.
    assert_eq!(
        small_response(511).validate().unwrap_err().code,
        PlatformErrorCode::InvalidArgument
    );
    let accepted = small_response(512);
    accepted.validate().unwrap();
    latent_control_store::RouteReadLimits {
        maximum_services: accepted.max_route_services,
        maximum_revisions: accepted.max_route_revisions,
        maximum_attributes_per_revision: accepted.max_metadata_entries,
        maximum_string_bytes: accepted.max_string_bytes,
        maximum_bytes: accepted.max_response_bytes,
    }
    .validate()
    .unwrap();
    ManagementLimits::default().validate().unwrap();
}
