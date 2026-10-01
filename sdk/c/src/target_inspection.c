#include "internal.h"
#include <string.h>

static bool id(latent_string value) {
    if (value.length == 0 || value.length > 512 || value.data == NULL) return false;
    for (size_t i=0; i<value.length; ++i) if ((unsigned char)value.data[i] <= 0x20 || (unsigned char)value.data[i] == 0x7f) return false;
    return true;
}
static bool digest(latent_string value, const char *prefix) {
    const size_t length=strlen(prefix);
    if (value.length != length+64 || value.data == NULL || memcmp(value.data,prefix,length) != 0) return false;
    for (size_t i=length; i<value.length; ++i) if (!((value.data[i]>='0' && value.data[i]<='9') || (value.data[i]>='a' && value.data[i]<='f'))) return false;
    return true;
}
static bool array(const void *values, size_t count, size_t maximum) { return count<=maximum && (count==0 || values!=NULL); }
static bool publication(const latent_profile_publication_ref *value, latent_string tenant) {
    return lsf_text_equal(value->tenant,tenant) && digest(value->id,"publication:sha256:");
}
static latent_string copy(latent_profile_call *call, size_t slot, latent_string value) {
    memcpy(call->target_selector_text[slot],value.data,value.length);
    return (latent_string){call->target_selector_text[slot],value.length};
}
bool lsf_target_request_valid(latent_profile_call *call, const latent_profile_inspect_http_target_request *value) {
    if (!id(value->service) || !id(value->contract) || !id(value->function) || (value->has_route && !id(value->route))
        || (value->has_revision_id && !id(value->revision_id)) || (value->has_routing_key && !id(value->routing_key)) || value->maximum_wait_millis>30000
        || (value->has_publication && !publication(&value->publication,call->owner->config.tenant))) return false;
    call->target_inspection=*value;
    latent_profile_inspect_http_target_request *owned=&call->target_inspection;
    owned->service=copy(call,0,value->service); owned->contract=copy(call,1,value->contract); owned->function=copy(call,2,value->function);
    if (value->has_route) owned->route=copy(call,3,value->route);
    if (value->has_revision_id) owned->revision_id=copy(call,4,value->revision_id);
    if (value->has_routing_key) owned->routing_key=copy(call,5,value->routing_key);
    if (value->has_publication) { owned->publication.id=copy(call,6,value->publication.id); owned->publication.tenant=call->owner->config.tenant; }
    return true;
}
static bool revision(const latent_profile_target_dependency_revision *value) { return id(value->id) && id(value->digest); }
static bool dependency(const latent_profile_target_dependency *value) {
    if (!id(value->capability) || !id(value->provider_profile) || !id(value->configuration_digest) || !digest(value->policy_identity_digest,"")
        || !value->has_binding || !revision(&value->binding) || !array(value->policies,value->policies_count,32)) return false;
    const latent_string state=value->state;
    if (!lsf_text_equal(state,LSF_TEXT("configured-current")) && !lsf_text_equal(state,LSF_TEXT("policy-changed-or-revoked"))
        && !lsf_text_equal(state,LSF_TEXT("provider-unavailable")) && !lsf_text_equal(state,LSF_TEXT("publication-unavailable"))
        && !lsf_text_equal(state,LSF_TEXT("route-changed-or-unavailable")) && !lsf_text_equal(state,LSF_TEXT("inspection-indeterminate"))) return false;
    for (size_t i=0; i<value->policies_count; ++i) if (!revision(&value->policies[i])) return false;
    return true;
}
static bool preparation(const latent_profile_target_preparation *value, bool included) {
    if ((included ? value->state==4 : value->state!=4) || !array(value->imports,value->imports_count,64) || !array(value->type_imports,value->type_imports_count,64)
        || value->imports_count > 64-value->type_imports_count || !array(value->exports,value->exports_count,128)
        || (value->has_engine_version && !id(value->engine_version)) || (value->has_target_triple && !id(value->target_triple))
        || (value->has_cpu_feature_set && !id(value->cpu_feature_set)) || (value->has_engine_configuration_digest && !digest(value->engine_configuration_digest,"blake3:"))
        || (value->has_sealed_metadata_fingerprint && !digest(value->sealed_metadata_fingerprint,""))
        || (value->has_diagnostic && (value->diagnostic.schema_version!=1 || (value->diagnostic.has_profile_digest && !digest(value->diagnostic.profile_digest,""))))) return false;
    for (size_t i=0; i<value->imports_count; ++i) if (!id(value->imports[i])) return false;
    for (size_t i=0; i<value->type_imports_count; ++i) if (!id(value->type_imports[i])) return false;
    for (size_t i=0; i<value->exports_count; ++i) if (!id(value->exports[i].contract) || !id(value->exports[i].function)) return false;
    return value->state!=1 || (value->has_profile && value->has_engine_version && value->has_engine_configuration_digest && value->has_target_triple
        && value->has_cpu_feature_set && value->has_declared_budget && value->has_import_count && value->import_count==value->imports_count+value->type_imports_count
        && value->has_function_count && value->function_count==value->exports_count && value->has_hostcall_fuel && value->has_maximum_lifted_bytes && value->has_maximum_type_nodes);
}
bool lsf_target_response_valid(const latent_profile_call *call, const latent_profile_inspect_http_target_response *value) {
    const latent_profile_inspect_http_target_request *request=&call->target_inspection;
    const latent_string tenant=call->owner->config.tenant;
    if (value->schema_version!=1 || !lsf_text_equal(value->tenant,tenant) || !lsf_text_equal(value->service,request->service)
        || !lsf_text_equal(value->contract,request->contract) || !lsf_text_equal(value->function,request->function) || !id(value->route)
        || (request->has_route && !lsf_text_equal(value->route,request->route)) || value->live_grants_checked || !array(value->candidates,value->candidates_count,32)) return false;
    bool selected=!value->has_selected_revision_id;
    for (size_t i=0; i<value->candidates_count; ++i) {
        const latent_profile_target_candidate *candidate=&value->candidates[i];
        if (!id(candidate->deployment_id) || !id(candidate->revision_id) || !digest(candidate->component_digest,"sha256:")
            || (candidate->has_package_digest && !digest(candidate->package_digest,"sha256:")) || (request->has_revision_id && !lsf_text_equal(candidate->revision_id,request->revision_id))
            || candidate->routing_weight>65535 || !array(candidate->reasons,candidate->reasons_count,16) || !array(candidate->dependencies,candidate->dependencies_count,32)
            || !array(candidate->http_bindings,candidate->http_bindings_count,32) || !candidate->has_preparation || !preparation(&candidate->preparation,request->include_preparation)
            || (candidate->has_publication && !publication(&candidate->publication,tenant)) || (candidate->has_requested_publication && !publication(&candidate->requested_publication,tenant))
            || (request->has_publication && (!candidate->has_publication || !lsf_text_equal(candidate->publication.id,request->publication.id)))) return false;
        for (size_t j=0; j<i; ++j) if (lsf_text_equal(candidate->revision_id,value->candidates[j].revision_id)) return false;
        if (candidate->has_publication_kind && (!candidate->has_package_digest || (!lsf_text_equal(candidate->publication_kind,LSF_TEXT("capsule"))
            && !lsf_text_equal(candidate->publication_kind,LSF_TEXT("browser-assets")) && !lsf_text_equal(candidate->publication_kind,LSF_TEXT("ssr-package"))))) return false;
        for (size_t j=0; j<candidate->http_bindings_count; ++j) {
            const latent_profile_inspected_http_binding *binding=&candidate->http_bindings[j];
            if (!id(binding->id) || binding->generation==0 || (!lsf_text_equal(binding->state,LSF_TEXT("configured-current")) && !lsf_text_equal(binding->state,LSF_TEXT("deployment-changed")))) return false;
        }
        for (size_t j=0; j<candidate->dependencies_count; ++j) if (!dependency(&candidate->dependencies[j])
            || (candidate->eligible && !lsf_text_equal(candidate->dependencies[j].state,LSF_TEXT("configured-current")))) return false;
        if (candidate->eligible && (value->state!=1 || !candidate->export_compatible || !candidate->has_publication || !candidate->has_package_digest
            || !candidate->has_publication_generation || candidate->routing_weight==0 || candidate->reasons_count!=1 || candidate->reasons[0]!=1
            || (candidate->preparation.state!=1 && candidate->preparation.state!=4))) return false;
        if (value->has_selected_revision_id && lsf_text_equal(value->selected_revision_id,candidate->revision_id)) selected=request->has_routing_key;
    }
    return selected;
}
