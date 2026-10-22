/* Ordinary pthread/C11 source port over the selected canonical C ABI.
 * Unselected source infrastructure: exact final-byte bootstrap/admission and
 * component routing verification are required before any engine can run it.
 */
#include <errno.h>
#include <pthread.h>
#include <threads.h>
#include <stdlib.h>
#include <string.h>
#include "thread-abi.h"

#undef pthread_equal
#undef thrd_equal

/* This is a bounded registry implementation limit, not an advertised runtime
 * Task ceiling. Original broker and Wasm-memory limits can refuse earlier.
 * Tombstones are not reused within an activation, preventing pointer ABA.
 */
#define RECORD_LIMIT 32u
#define STACK_BYTES 65536u
#define TEMPLATE_LIMIT (1024u*1024u)

_Static_assert(sizeof(pthread_t)==sizeof(void *),"unsupported pthread handle ABI");
_Static_assert(sizeof(thrd_t)==sizeof(pthread_t),"unsupported C11 thread ABI");

struct token_result { uint8_t tag; uint8_t pad[7]; union { struct lsf_c_token token; uint8_t error; } value; };
struct unit_result { uint8_t tag,error; };
_Static_assert(sizeof(struct token_result)==24 && offsetof(struct token_result,value)==8,
               "unsupported canonical register lowering");

__attribute__((import_module("latent:runtime/activation@0.1.0"),import_name("register")))
void host_register(uint32_t,uint32_t,uint64_t,uint64_t,struct token_result *);
__attribute__((import_module("latent:runtime/activation@0.1.0"),import_name("settle")))
void host_settle(uint64_t,uint64_t,struct unit_result *);
__attribute__((import_module("latent:runtime/activation@0.1.0"),import_name("park")))
void host_park(uint64_t,uint64_t,struct unit_result *);
__attribute__((import_module("latent:runtime/activation@0.1.0"),import_name("wake")))
void host_wake(uint64_t,uint64_t,struct unit_result *);

static void require(int predicate) { if (!predicate) __builtin_trap(); }
static int token_live(struct lsf_c_token value) { return value.generation!=0 && value.id!=0; }
static int runtime_error(unsigned error) {
    switch (error) {
    case 0: return ENOTSUP;
    case 1: return EPERM;
    case 2: return EAGAIN;
    case 3: return ECANCELED;
    case 4: return ETIMEDOUT;
    case 5: case 6: return EINVAL;
    default: __builtin_trap();
    }
}
static int acquire(unsigned kind,const struct lsf_c_token *continuation,struct lsf_c_token *out) {
    struct token_result result={0};
    host_register(kind,continuation!=NULL,continuation?continuation->generation:0,
                  continuation?continuation->id:0,&result);
    if (result.tag==1) return runtime_error(result.value.error);
    require(result.tag==0 && token_live(result.value.token));
    *out=result.value.token;return 0;
}
static void settle(struct lsf_c_token *token) {
    if (!token_live(*token)) return;
    struct unit_result result={255,255};host_settle(token->generation,token->id,&result);
    require(result.tag==0);*token=(struct lsf_c_token){0};
}
static void park(struct lsf_c_token token) {
    struct unit_result result={255,255};host_park(token.generation,token.id,&result);require(result.tag==0);
}
static void wake(struct lsf_c_token token) {
    struct unit_result result={255,255};host_wake(token.generation,token.id,&result);require(result.tag==0);
}
static struct lsf_c_thread *current(void) {
    struct lsf_c_thread *thread=lsf_c_context_get();
    require(thread!=NULL && thread->phase==LSF_C_RUNNING && thread->root!=NULL
            && thread->canonical_id==lsf_c_thread_index());
    return thread;
}
static struct lsf_c_thread *find(pthread_t identity) {
    struct lsf_c_thread *root=current()->root,*thread=root;
    unsigned visited=0;
    do {
        require(++visited<=RECORD_LIMIT+1u);
        if ((pthread_t)(uintptr_t)thread==identity) return thread;
        thread=thread->next;
    } while (thread!=NULL);
    return NULL;
}
static int ensure_root_owners(struct lsf_c_thread *root) {
    if (token_live(root->task)) return 0;
    struct lsf_c_token task={0},owner={0};
    int error=acquire(LSF_C_TASK,NULL,&task);
    if (!error) error=acquire(LSF_C_NATIVE,&task,&owner);
    if (error) { settle(&task);return error; }
    root->task=task;root->context_owner=owner;return 0;
}

int __lsf_c_root_initialize(struct lsf_c_thread *root,uint32_t extent) {
    require(root==lsf_c_context_get() && root->phase==LSF_C_RUNNING
            && root->low!=0 && root->low%16u==0 && root->high%16u==0 && root->high>root->low
            && extent==root->tls_bytes && extent>0 && extent<=TEMPLATE_LIMIT);
    root->root=root;root->initial_template=NULL;root->api=LSF_C_ROOT;
    root->canonical_id=lsf_c_thread_index();return 0;
}

__attribute__((export_name("__lsf_c_template_copy")))
void __lsf_c_template_copy(void *destination) {
    (void)destination;__builtin_trap();
}
static int ensure_template(struct lsf_c_thread *root) {
    if (root->initial_template!=NULL) return 0;
    require(token_live(root->task) && token_live(root->context_owner));
    size_t size=(root->tls_bytes+15u)&~(size_t)15u;
    void *copy=aligned_alloc(16,size);
    if (copy==NULL) return ENOMEM;
    /* Fixed memory.init reads a private passive segment reconstructed from
     * authenticated original data, never root TLS after constructors ran.
     * A trap retains the admitted owners/allocation through StoreDrop.
     */
    __lsf_c_template_copy(copy);root->initial_template=copy;return 0;
}

static void discard_unstarted(struct lsf_c_thread *thread) {
    require(thread!=NULL && thread->creation_started==0);
    free(thread->tls_allocation);free(thread->stack_allocation);
    settle(&thread->result_owner);settle(&thread->context_owner);settle(&thread->task);free(thread);
}

/* The post-link fixed entry body replaces this deliberate refusal. Merely
 * linking the C symbols cannot turn source infrastructure into a running PAL.
 */
__attribute__((export_name("__lsf_c_owned_thread_entry")))
void __lsf_c_owned_thread_entry(struct lsf_c_thread *thread) {
    (void)thread;__builtin_trap();
}

static int create(struct lsf_c_thread **out,void *(*pthread_start)(void *),
                  int (*c11_start)(void *),void *argument,unsigned api) {
    struct lsf_c_thread *caller=current(),*root=caller->root;
    if (root->closing || root->started_count>=RECORD_LIMIT) return EAGAIN;
    int error=ensure_root_owners(root);
    if (error) return error;
    error=ensure_template(root);
    if (error) return error;
    struct lsf_c_token task={0},owner={0},result={0};
    error=acquire(LSF_C_TASK,&caller->task,&task);
    if (!error) error=acquire(LSF_C_NATIVE,&task,&owner);
    if (!error) error=acquire(LSF_C_RESULT,&task,&result);
    if (error) { settle(&result);settle(&owner);settle(&task);return error; }
    /* All logical owners exist BEFORE any context, stack or TLS allocation.
     * Linear allocations remain under the original Wasm memory limiter.
     * The allocator/registry cannot contain suspension checkpoints.
     */
    size_t bytes=(sizeof(struct lsf_c_thread)+15u)&~(size_t)15u;
    struct lsf_c_thread *thread=aligned_alloc(16,bytes);
    if (thread==NULL) { settle(&result);settle(&owner);settle(&task);return ENOMEM; }
    memset(thread,0,bytes);thread->task=task;thread->context_owner=owner;thread->result_owner=result;
    thread->stack_allocation=aligned_alloc(16,STACK_BYTES);
    size_t extent=(root->tls_bytes+15u)&~(size_t)15u;
    thread->tls_allocation=aligned_alloc(16,extent);
    if (thread->stack_allocation==NULL || thread->tls_allocation==NULL) {
        discard_unstarted(thread);return ENOMEM;
    }
    uintptr_t low=(uintptr_t)thread->stack_allocation,tls=(uintptr_t)thread->tls_allocation;
    require(low!=0 && low%16u==0 && low<=UINT32_MAX-STACK_BYTES && tls!=0 && tls%16u==0
            && extent<=UINT32_MAX-tls && extent>=root->tls_bytes);
    memset(thread->stack_allocation,0,STACK_BYTES);
    memcpy(thread->tls_allocation,root->initial_template,root->tls_bytes);
    thread->sp=thread->high=(uint32_t)low+STACK_BYTES;thread->low=(uint32_t)low;
    thread->tls=(uint32_t)tls;thread->tls_bytes=root->tls_bytes;thread->phase=LSF_C_PREPARED;
    thread->parent=caller->canonical_id;thread->api=api;thread->argument=argument;thread->root=root;
    if (api==LSF_C_PTHREAD) thread->start.pthread=pthread_start;else thread->start.c11=c11_start;
    thread->admission[0]=thread->admission[1]=255;
    uint32_t canonical=lsf_c_thread_new((uint32_t)(uintptr_t)&__lsf_c_owned_thread_entry,thread);
    if (thread->creation_started==0) {
        require(thread->admission[0]==1);error=runtime_error(thread->admission[1]);
        discard_unstarted(thread);return error;
    }
    require(thread->creation_started==1 && thread->admission[0]==0 && canonical!=caller->canonical_id);
    thread->canonical_id=canonical;thread->next=root->next;root->next=thread;++root->started_count;
    /* A real child runs only its context/identity handshake, then yields back.
     * No user start function runs inline in pthread_create/thrd_create.
     */
    (void)lsf_c_thread_switch(canonical);
    require(current()==caller && thread->creation_started==2 && thread->phase==LSF_C_RUNNING);
    *out=thread;return 0;
}

int pthread_create(pthread_t *restrict out,const pthread_attr_t *restrict attr,
                   void *(*start)(void *),void *restrict argument) {
    int saved=errno,error;struct lsf_c_thread *thread=NULL;
    if (out==NULL || start==NULL) error=EINVAL;
    else if (attr!=NULL) error=ENOTSUP;
    else error=create(&thread,start,NULL,argument,LSF_C_PTHREAD);
    if (error==ENOMEM) error=EAGAIN;
    if (!error) *out=(pthread_t)(uintptr_t)thread;
    errno=saved;return error;
}
int thrd_create(thrd_t *out,thrd_start_t start,void *argument) {
    int saved=errno,error;struct lsf_c_thread *thread=NULL;
    error=out==NULL || start==NULL?EINVAL:create(&thread,NULL,start,argument,LSF_C_C11);
    if (!error) *out=(thrd_t)(uintptr_t)thread;
    errno=saved;return error==0?thrd_success:(error==ENOMEM || error==EAGAIN)?thrd_nomem:thrd_error;
}
pthread_t pthread_self(void) { return (pthread_t)(uintptr_t)current(); }
int pthread_equal(pthread_t a,pthread_t b) { return a==b; }
thrd_t thrd_current(void) { return (thrd_t)(uintptr_t)current(); }
int thrd_equal(thrd_t a,thrd_t b) { return a==b; }

static int join(pthread_t identity,unsigned api,struct lsf_c_thread **out) {
    struct lsf_c_thread *caller=current(),*thread=find(identity);
    if (thread==NULL) return ESRCH;
    if (thread==caller) return EDEADLK;
    if (thread->api==LSF_C_ROOT || thread->api!=api || thread->joined || thread->joiner) return EINVAL;
    /* Follow only registry-owned identities, before acquiring a Wait or
     * publishing a join claim. A genuine cycle is an error, not a successful
     * join or a manufactured thread completion.
     */
    struct lsf_c_thread *dependency=thread;unsigned depth=0;
    while (dependency!=NULL) {
        if (dependency==caller) return EDEADLK;
        require(++depth<=RECORD_LIMIT+1u);
        struct lsf_c_thread *next=dependency->waiting_for;
        require(next==NULL || find((pthread_t)(uintptr_t)next)==next);
        dependency=next;
    }
    require(caller->waiting_for==NULL);
    struct lsf_c_token wait={0};int error=acquire(LSF_C_WAIT,&caller->task,&wait);
    if (error) return error;
    thread->joiner=(uint32_t)(uintptr_t)caller;caller->waiting_for=thread;
    while (thread->phase!=LSF_C_FRAMES_EXITED) {
        park(caller->task);(void)lsf_c_thread_switch(thread->canonical_id);wake(caller->task);
        require(current()==caller);
    }
    require(thread->tls_finished==1 && thread->sp==thread->high);
    /* Only final translated C/TLS frame completion permits logical retirement.
     * Engine stack/metadata reservations remain owned until actual StoreDrop.
     */
    thread->joined=1;caller->waiting_for=NULL;settle(&wait);
    free(thread->tls_allocation);thread->tls_allocation=NULL;
    free(thread->stack_allocation);thread->stack_allocation=NULL;
    settle(&thread->context_owner);settle(&thread->task);settle(&thread->result_owner);
    *out=thread;return 0;
}
int pthread_join(pthread_t identity,void **result) {
    int saved=errno;struct lsf_c_thread *thread=NULL;int error=join(identity,LSF_C_PTHREAD,&thread);
    if (!error && result!=NULL) *result=thread->result.pthread;
    errno=saved;return error;
}
int thrd_join(thrd_t identity,int *result) {
    int saved=errno;struct lsf_c_thread *thread=NULL;int error=join((pthread_t)(uintptr_t)identity,LSF_C_C11,&thread);
    if (!error && result!=NULL) *result=thread->result.c11;
    errno=saved;return error?thrd_error:thrd_success;
}
int pthread_detach(pthread_t identity) {
    int saved=errno;int error=find(identity)==NULL?ESRCH:ENOTSUP;errno=saved;return error;
}
int thrd_detach(thrd_t identity) {
    int saved=errno;(void)identity;errno=saved;return thrd_error;
}

__attribute__((export_name("__lsf_c_thread_body")))
void __lsf_c_thread_body(struct lsf_c_thread *thread) {
    require(current()==thread && thread->creation_started==1);
    thread->creation_started=2;
    (void)lsf_c_thread_switch(thread->parent);
    require(current()==thread);
    if (thread->api==LSF_C_PTHREAD) thread->result.pthread=thread->start.pthread(thread->argument);
    else { require(thread->api==LSF_C_C11);thread->result.c11=thread->start.c11(thread->argument); }
    require(lsf_c_tls_finish()==0);thread->tls_finished=1;
    /* Keep phase RUNNING through the actual final C epilogue. Only the fixed
     * stackless entry validates restored SP, marks FRAMES_EXITED and detaches.
     */
}

void __lsf_c_root_finish(struct lsf_c_thread *root) {
    require(current()==root && root->api==LSF_C_ROOT && !root->closing);
    root->closing=1;
    for (struct lsf_c_thread *thread=root->next;thread!=NULL;thread=thread->next) {
        if (!thread->joined) {
            struct lsf_c_thread *joined=NULL;
            require(join((pthread_t)(uintptr_t)thread,thread->api,&joined)==0 && joined==thread);
        }
    }
    require(lsf_c_tls_finish()==0);root->tls_finished=1;
    /* Tombstones stay valid until there can be no further application access.
     * The fixed stackless root wrapper settles these exact logical tokens only
     * after this C frame and its TLS destructors have returned. Physical host
     * stack/metadata owners remain charged independently through StoreDrop.
     */
}

/* Shares the private current-thread and original-ledger operations above. */
#include "synchronization.c"
