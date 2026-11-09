/* Explicit lost response and fresh-client recovery against a provisioned node. */
#include <latent/transaction_client.h>
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#define TEXT(s) ((latent_string){s, sizeof(s)-1u})
#define BYTES(s) ((latent_bytes){(const uint8_t *)(s), sizeof(s)-1u})
static const char *required(const char *name) { const char *v=getenv(name); if (!v || !*v) { fprintf(stderr,"missing fixture field %s\n",name); exit(2); } return v; }
static latent_string str(const char *v) { return (latent_string){v,strlen(v)}; }
static int digit(char c) { if (c >= '0' && c <= '9') return c-'0'; if (c >= 'a' && c <= 'f') return c-'a'+10; return -1; }
static bool equal_hex(const uint8_t *v, size_t n, const char *hex) { if (strlen(hex)!=n*2) return false; for(size_t i=0;i<n;i++) { int a=digit(hex[2*i]),b=digit(hex[2*i+1]); if(a<0 || b<0 || v[i]!=(uint8_t)(a*16+b)) return false; } return true; }
typedef struct observed { unsigned calls; } observed;
static void invoked(const latent_transaction_invoke_command_result *r, const latent_transaction_client_failure *f, void *ctx) {
    observed *o=ctx; assert(o->calls++ == 0 && r==NULL && f);
    assert(f->transport.dispatched && f->transport.outcome==LATENT_PROFILE_OUTCOME_KNOWLEDGE_UNKNOWN);
    assert(f->identity.command && f->identity.command->client_key.length==strlen("c-sdk-lost-response") &&
        memcmp(f->identity.command->client_key.data,"c-sdk-lost-response",strlen("c-sdk-lost-response"))==0 && !f->observed.has_command);
    const char *cancellation=getenv("LSF_401_CANCEL_AFTER_DISPATCH");
    if (cancellation && strcmp(cancellation,"1")==0) {
        assert(f->transport.category==LATENT_PROFILE_FAILURE_CATEGORY_LOCAL_CANCELLED);
        puts("CANCELLED_COMMIT_UNKNOWN");
    }
    puts("LOST_RESPONSE_UNKNOWN");
}
static bool matches(latent_string s,const char *v) { size_t n=strlen(v); return s.length==n && memcmp(s.data,v,n)==0; }
static void recovered(const latent_transaction_lookup_command_result *r, const latent_transaction_client_failure *f, void *ctx) {
    observed *o=ctx; assert(o->calls++ == 0 && f==NULL && r && r->value.has_command);
    const latent_transaction_command_inspection *c=&r->value.command;
    assert(c->outcome==LATENT_TRANSACTION_COMMAND_OUTCOME_COMMITTED && c->metadata_durable && c->application_state_committed && c->has_commit && c->commit.effect_ids_count==1);
    assert(matches(c->command_id,required("LSF_401_ORIGINAL_ID")) && matches(c->attempt_id,required("LSF_401_ORIGINAL_ATTEMPT")));
    assert(equal_hex(c->fingerprint_sha256.data,c->fingerprint_sha256.length,required("LSF_401_ORIGINAL_FINGERPRINT")));
    assert(matches(c->commit.receipt_id,required("LSF_401_ORIGINAL_RECEIPT")) && matches(c->commit.effect_ids[0],required("LSF_401_ORIGINAL_EFFECT")));
    puts("LOST_COMMIT_RECOVERED");
}
static bool contains_bytes(latent_bytes haystack, const char *needle) {
    size_t n=strlen(needle); if (haystack.length<n) return false;
    for (size_t i=0; i<=haystack.length-n; ++i) if (memcmp(haystack.data+i,needle,n)==0) return true;
    return false;
}
static void queried(const latent_transaction_query_result *r, const latent_transaction_client_failure *f, void *ctx) {
    observed *o=ctx; assert(o->calls++ == 0 && r && !f);
    assert(!r->metadata.observed.has_command && !r->metadata.observed.effect && !r->metadata.observed.state);
    const latent_transaction_query_response *v=&r->value;
    assert(v->has_view && v->view.has_namespace && v->has_source && v->has_invocation && v->invocation.has_success);
    assert(matches(v->view.namespace.tenant,required("LSF_401_TENANT")) && matches(v->view.namespace.namespace,required("LSF_401_NAMESPACE")) && matches(v->view.namespace.incarnation,required("LSF_401_INCARNATION")));
    assert(equal_hex(v->view.version.data,v->view.version.length,required("LSF_401_QUERY_MINIMUM_HEX")));
    assert(!v->invocation.success.has_committed_state_version && v->invocation.success.effect_ids_count==0);
    assert(contains_bytes(v->invocation.success.payload,"\"count\":\"2\""));
}
static void wait(latent_transport *owner, observed *o) { for(unsigned i=0; o->calls==0 && i<1000; ++i) assert(latent_transport_poll(owner,10)); assert(o->calls==1); }
static void close_owner(latent_transport *owner) { assert(latent_transport_shutdown(owner,1000)); latent_transport_usage u=latent_transport_get_usage(owner); assert(u.stopped && !u.sockets && !u.sessions && !u.in_flight && !u.queued && !u.retained_calls && !u.callbacks_pending && !u.http2_bytes); assert(latent_transport_destroy(owner)); }
int main(void) {
    const char *tenant=required("LSF_401_TENANT"), *token=required("LSF_401_TOKEN"); char url[300]; int written=snprintf(url,sizeof(url),"http://%s",required("LSF_401_ENDPOINT")); assert(written>0 && (size_t)written<sizeof(url));
    latent_transport_config config=latent_transport_defaults(); config.endpoint=str(url); config.tenant=str(tenant); config.bearer_token=(latent_bytes){(const uint8_t *)token,strlen(token)};
    const char *cancellation=getenv("LSF_401_CANCEL_AFTER_DISPATCH");
    bool cancel_after_dispatch=cancellation && strcmp(cancellation,"1")==0;
    if (cancel_after_dispatch) config.timeout_millis=15000;
    latent_transport *owner=NULL; assert(latent_transport_create(&config,&owner,NULL)); const latent_transaction_client_vtable *api=latent_transport_transaction_vtable();
    latent_transaction_command_selector selector={.has_namespace=true,.namespace={str(tenant),str(required("LSF_401_NAMESPACE")),str(required("LSF_401_INCARNATION"))},.operation=TEXT("update"),.client_key=TEXT("c-sdk-lost-response")};
    observed out={0}; latent_profile_call *call;
    if (strcmp(required("LSF_401_MODE"),"query")==0) {
        const char *hex=required("LSF_401_QUERY_MINIMUM_HEX"); size_t len=strlen(hex); assert(len && len%2==0 && len<=512); uint8_t version[256];
        for(size_t i=0;i<len/2;i++) { int a=digit(hex[i*2]),b=digit(hex[i*2+1]); assert(a>=0 && b>=0); version[i]=(uint8_t)(a*16+b); }
        for (unsigned i=0; i<3; ++i) {
            char activation[40]; int n=snprintf(activation,sizeof(activation),"c-sdk-fresh-query-%u",i); assert(n>0 && (size_t)n<sizeof(activation));
            latent_transaction_query_request req={.has_profile=true,.profile=latent_transaction_current_profile(),.has_namespace=true,.namespace=selector.namespace,.has_minimum_view_version=true,.minimum_view_version={version,len/2},
                .has_invocation=true,.invocation={.has_activation_id=true,.activation_id=str(activation),.has_target=true,.target={.tenant=str(tenant),.service=TEXT("examples/transaction-java-aggregate"),.contract=TEXT("examples:transactional-aggregate/api@1.0.0"),.function=TEXT("query"),.has_route=true,.route=TEXT("transaction-java-aggregate")},.payload=BYTES("[]"),.media_type=TEXT("application/vnd.latent.wit-values.v1+json"),.has_budget=true,.budget={.cpu_fuel=1000000000,.memory_bytes=67108864,.state_read_bytes=4194304,.has_wall_time_limit_millis=true,.wall_time_limit_millis=120000}}};
            out=(observed){0}; call=api->query(latent_transport_transaction(owner),&req,NULL,queried,&out); assert(call); wait(owner,&out); api->release_call(call);
        }
        close_owner(owner); puts("FRESH_QUERY_AFTER_COMMIT"); return 0;
    }
    if (strcmp(required("LSF_401_MODE"),"recover")==0) {
        latent_transaction_lookup_command_request req={.has_profile=true,.profile=latent_transaction_current_profile(),.has_command=true,.command=selector,.has_authorization_publication=true,.authorization_publication={.id=str(required("LSF_401_PUBLICATION")),.tenant=str(tenant)}};
        call=api->lookup_command(latent_transport_transaction(owner),&req,NULL,recovered,&out);
    } else {
        assert(strcmp(required("LSF_401_MODE"),"invoke")==0); const char *hex=required("LSF_401_EXPECTED_VERSION_HEX"); size_t len=strlen(hex); assert(len && len%2==0 && len<=512); uint8_t version[256];
        for(size_t i=0;i<len/2;i++) { int a=digit(hex[i*2]),b=digit(hex[i*2+1]); assert(a>=0 && b>=0); version[i]=(uint8_t)(a*16+b); }
        latent_transaction_expected_version expected={.key=BYTES("aggregate/count"),.has_version=true,.version={version,len/2}};
        latent_transaction_invoke_command_request req={.has_profile=true,.profile=latent_transaction_current_profile(),.has_command=true,.command=selector,.input_format=TEXT("lsf-wit-values-v1"),.expected_versions=&expected,.expected_versions_count=1,
            .has_invocation=true,.invocation={.has_activation_id=true,.activation_id=TEXT("c-sdk-lost-response"),.has_target=true,.target={.tenant=str(tenant),.service=TEXT("examples/transaction-java-aggregate"),.contract=TEXT("examples:transactional-aggregate/api@1.0.0"),.function=TEXT("update"),.has_route=true,.route=TEXT("transaction-java-aggregate")},.payload=BYTES("[{\"delta\":1,\"reject\":false}]"),.media_type=TEXT("application/vnd.latent.wit-values.v1+json"),.has_budget=true,.budget={.cpu_fuel=1000000000,.memory_bytes=67108864,.state_read_bytes=4194304,.state_write_bytes=2097152,.effect_count=1,.has_wall_time_limit_millis=true,.wall_time_limit_millis=120000}}};
        call=api->invoke_command(latent_transport_transaction(owner),&req,NULL,invoked,&out); assert(call);
        if (cancel_after_dispatch) {
            struct timespec begin, now; assert(clock_gettime(CLOCK_MONOTONIC,&begin)==0);
            do { assert(latent_transport_poll(owner,10)); assert(out.calls==0); assert(clock_gettime(CLOCK_MONOTONIC,&now)==0); } while ((now.tv_sec-begin.tv_sec)*1000000000LL + now.tv_nsec-begin.tv_nsec < 5000000000LL);
            api->cancel_local(call);
        }
        wait(owner,&out); api->release_call(call); close_owner(owner); return 0;
    }
    assert(call); wait(owner,&out); api->release_call(call); close_owner(owner); return 0;
}
