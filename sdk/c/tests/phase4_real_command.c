/* Explicit version-fenced command against a separately provisioned node. */
#include <latent/transaction_client.h>
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define TEXT(s) ((latent_string){s, sizeof(s)-1u})
#define BYTES(s) ((latent_bytes){(const uint8_t *)(s), sizeof(s)-1u})
static const char *required(const char *name) { const char *v=getenv(name); if (!v || !*v) { fprintf(stderr,"missing fixture field %s\n",name); exit(2); } return v; }
static latent_string str(const char *v) { return (latent_string){v,strlen(v)}; }
static int digit(char c) { if (c >= '0' && c <= '9') return c-'0'; if (c >= 'a' && c <= 'f') return c-'a'+10; return -1; }
typedef struct observed { unsigned calls; bool failed; } observed;
static void invoked(const latent_transaction_invoke_command_result *r, const latent_transaction_client_failure *f, void *ctx) {
    observed *o=ctx; assert(o->calls++ == 0 && ((r==NULL)!=(f==NULL))); o->failed=f!=NULL;
    if (f) { fprintf(stderr,"DIAGNOSTIC category=%d outcome=%d dispatched=%d\n",f->transport.category,f->transport.outcome,(int)f->transport.dispatched); return; }
    const latent_transaction_command_inspection *c=&r->value.command;
    assert(r->value.has_command && c->outcome==LATENT_TRANSACTION_COMMAND_OUTCOME_COMMITTED && c->metadata_durable && c->application_state_committed && c->has_commit && c->commit.effect_ids_count==1);
    printf("RESULT %.*s %.*s %.*s\n",(int)c->command_id.length,c->command_id.data,(int)c->attempt_id.length,c->attempt_id.data,(int)c->commit.effect_ids[0].length,c->commit.effect_ids[0].data);
}
static void recovered(const latent_transaction_lookup_command_result *r, const latent_transaction_client_failure *f, void *ctx) {
    observed *o=ctx; assert(o->calls++==0 && ((r==NULL)!=(f==NULL))); o->failed=f!=NULL;
    if (f) { fprintf(stderr,"RECOVERY_FAILED category=%d\n",f->transport.category); return; }
    const latent_transaction_command_inspection *c=&r->value.command;
    assert(r->value.has_command && c->has_commit);
    fprintf(stderr,"RECOVERY outcome=%d durable=%d committed=%d effects=%zu\n",c->outcome,(int)c->metadata_durable,(int)c->application_state_committed,c->commit.effect_ids_count);
}
static void wait(latent_transport *owner, observed *o) { for (unsigned i=0; o->calls==0 && i<1000; ++i) assert(latent_transport_poll(owner,10)); assert(o->calls==1); }
static void close_owner(latent_transport *owner) { assert(latent_transport_shutdown(owner,1000)); latent_transport_usage u=latent_transport_get_usage(owner); assert(u.stopped && !u.sockets && !u.sessions && !u.in_flight && !u.queued && !u.retained_calls && !u.callbacks_pending && !u.http2_bytes); assert(latent_transport_destroy(owner)); }
int main(void) {
    const char *tenant=required("LSF_401_TENANT"), *token=required("LSF_401_TOKEN"), *hex=required("LSF_401_EXPECTED_VERSION_HEX");
    size_t len=strlen(hex); assert(len && len%2==0 && len<=512); uint8_t version[256];
    for (size_t i=0;i<len/2;i++) { int a=digit(hex[i*2]),b=digit(hex[i*2+1]); assert(a>=0 && b>=0); version[i]=(uint8_t)(a*16+b); }
    char url[300]; int written=snprintf(url,sizeof(url),"http://%s",required("LSF_401_ENDPOINT")); assert(written>0 && (size_t)written<sizeof(url));
    latent_transport_config config=latent_transport_defaults(); config.endpoint=str(url); config.tenant=str(tenant); config.bearer_token=(latent_bytes){(const uint8_t *)token,strlen(token)};
    latent_transport *owner=NULL; assert(latent_transport_create(&config,&owner,NULL));
    const latent_transaction_client_vtable *api=latent_transport_transaction_vtable();
    latent_transaction_command_selector selector={.has_namespace=true,.namespace={str(tenant),str(required("LSF_401_NAMESPACE")),str(required("LSF_401_INCARNATION"))},.operation=TEXT("update"),.client_key=TEXT("c-sdk-direct-command")};
    latent_transaction_expected_version expected={.key=BYTES("aggregate/count"),.has_version=true,.version={version,len/2}};
    latent_transaction_invoke_command_request req={.has_profile=true,.profile=latent_transaction_current_profile(),.has_command=true,.command=selector,.input_format=TEXT("lsf-wit-values-v1"),.expected_versions=&expected,.expected_versions_count=1,
      .has_invocation=true,.invocation={.has_activation_id=true,.activation_id=TEXT("c-sdk-direct-command"),.has_target=true,.target={.tenant=str(tenant),.service=TEXT("examples/transaction-java-aggregate"),.contract=TEXT("examples:transactional-aggregate/api@1.0.0"),.function=TEXT("update"),.has_route=true,.route=TEXT("transaction-java-aggregate")},
      .payload=BYTES("[{\"delta\":1,\"reject\":false}]"),.media_type=TEXT("application/vnd.latent.wit-values.v1+json"),.has_budget=true,.budget={.cpu_fuel=1000000000,.memory_bytes=67108864,.state_read_bytes=4194304,.state_write_bytes=2097152,.effect_count=1,.has_wall_time_limit_millis=true,.wall_time_limit_millis=120000}}};
    observed first={0}; latent_profile_call *call=api->invoke_command(latent_transport_transaction(owner),&req,NULL,invoked,&first); assert(call); wait(owner,&first); api->release_call(call); close_owner(owner);
    if (first.failed) {
        latent_transport *recovery=NULL; assert(latent_transport_create(&config,&recovery,NULL));
        latent_transaction_lookup_command_request lookup={.has_profile=true,.profile=latent_transaction_current_profile(),.has_command=true,.command=selector,.has_authorization_publication=true,.authorization_publication={.id=str(required("LSF_401_PUBLICATION")),.tenant=str(tenant)}};
        observed out={0}; call=api->lookup_command(latent_transport_transaction(recovery),&lookup,NULL,recovered,&out); assert(call); wait(recovery,&out); api->release_call(call); close_owner(recovery); return 1;
    }
    return 0;
}
