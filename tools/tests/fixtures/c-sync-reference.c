/* Serialized source controls only. Broker/canonical ports below are explicit
 * doubles; this is neither a Wasmtime guest nor original-ledger qualification.
 * The native reference uses exact extracted public memory32 typedefs and
 * constants, with freestanding native compiler headers. The actual WASI-header object is a
 * separate unchanged-source compile; no hybrid native/WASI libc is claimed.
 */
#include <stdint.h>
#include <stddef.h>
#include "c-sync-reference-abi.h"
#include "thread-abi.h"
struct timespec;
static unsigned case_index;
/* Freestanding native reference: do not build a second CRT/sysroot merely to
 * execute these bounded controls. These Win32 calls are test-runner output
 * and process-exit ports, never part of the selected guest runtime.
 */
#if defined(__wasm__)
__attribute__((import_module("lsf-source-test"),import_name("exit")))
void ExitProcess(unsigned);
__attribute__((import_module("lsf-source-test"),import_name("write")))
void source_write(const char *,unsigned);
#else
__declspec(dllimport) void __stdcall ExitProcess(unsigned);
__declspec(dllimport) void *__stdcall GetStdHandle(unsigned);
__declspec(dllimport) int __stdcall WriteFile(void *,const void *,unsigned,unsigned *,void *);
#endif
static void *memcpy(void *destination,const void *source,size_t size) {
    unsigned char *out=destination;const unsigned char *in=source;
    for (size_t index=0;index<size;++index) out[index]=in[index];return destination;
}
static void *memset(void *destination,int value,size_t size) {
    unsigned char *out=destination;
    for (size_t index=0;index<size;++index) out[index]=(unsigned char)value;return destination;
}
static void abort(void) { ExitProcess(100+case_index);__builtin_unreachable(); }
static int printf(const char *text,...) {
    unsigned size=0;while (text[size]) ++size;
#if defined(__wasm__)
    source_write(text,size);return (int)size;
#else
    unsigned written=0;
    (void)WriteFile(GetStdHandle((unsigned)-11),text,size,&written,NULL);return (int)written;
#endif
}

static struct lsf_c_thread root,child,*active;
static unsigned live,admissions,returns,parks,wakes,suspends,resumes,capacity;
static unsigned released,freed;
static void (*on_park)(void),(*on_suspend)(void),(*on_admit)(void);
static pthread_mutex_t mutex;
static pthread_cond_t condition;
static int observed;
static int source_errno;
static void callback(void (*function)(void));
#undef errno
#define errno source_errno
int *__errno_location(void) { return &source_errno; }
static void require(int value) { if (!value) abort(); }
static struct lsf_c_thread *current(void) { return active; }
static int ensure_root_owners(struct lsf_c_thread *value) {
    if (!value->task.id) value->task=(struct lsf_c_token){1,7};return 0;
}
static int acquire(unsigned kind,const struct lsf_c_token *parent,struct lsf_c_token *out) {
    require(kind==LSF_C_WAIT && parent && parent->id);
    ++admissions;if (live==capacity) return EAGAIN;
    ++live;*out=(struct lsf_c_token){1,admissions+10};
    if (on_admit) { void (*function)(void)=on_admit;on_admit=NULL;callback(function); }
    return 0;
}
static void settle(struct lsf_c_token *token) {
    if (token->id>=1000) { ++released;*token=(struct lsf_c_token){0};return; }
    require(token->id && live);--live;++returns;*token=(struct lsf_c_token){0};
}
static void callback(void (*function)(void)) {
    struct lsf_c_thread *saved=active;active=&child;function();active=saved;
}
static void park(struct lsf_c_token token) {
    require(token.id);++parks;
    if (on_park) { void (*function)(void)=on_park;on_park=NULL;callback(function); }
}
static void wake(struct lsf_c_token token) { require(token.id);++wakes; }
#include "synchronization.c"
uint32_t __lsf_c_sync_suspend(void) {
    ++suspends;require(on_suspend!=NULL);
    void (*function)(void)=on_suspend;on_suspend=NULL;callback(function);return 0;
}
void __lsf_c_sync_resume_later(uint32_t index) {
    require(index==root.canonical_id);++resumes;
}
#define RECORD_LIMIT 32u
static void free(void *allocation) { require(allocation!=NULL);++freed; }
/* The runner extracts these actual unchanged functions from threads.c. */
#include "c-join-reference-body.h"

#define CHECK(value) do { if (!(value)) { printf("FAIL:%s:%d\n",__func__,__LINE__);return 1; } } while (0)
static void reset(void) {
    root=(struct lsf_c_thread){.canonical_id=11,.phase=LSF_C_RUNNING};root.root=&root;
    child=(struct lsf_c_thread){.canonical_id=12,.root=&root,.task={1,1000},
        .context_owner={1,1001},.result_owner={1,1002},.api=LSF_C_PTHREAD,
        .phase=LSF_C_RUNNING,.high=65536,.stack_allocation=&mutex,.tls_allocation=&condition};
    root.next=&child;
    active=&root;live=admissions=returns=parks=wakes=suspends=resumes=0;
    capacity=1;on_park=on_suspend=on_admit=NULL;observed=0;source_errno=37;released=freed=0;
    memset(&mutex,0,sizeof(mutex));memset(&condition,0,sizeof(condition));
}
static void child_unlock(void) { require(pthread_mutex_unlock(&mutex)==0); }
static void child_signal_held(void) {
    require(pthread_mutex_lock(&mutex)==0);
    require(pthread_cond_signal(&condition)==0);
    observed=1;on_suspend=child_unlock;
}
static void child_signal_unlock(void) {
    require(pthread_mutex_lock(&mutex)==0);
    require(pthread_cond_signal(&condition)==0);
    require(pthread_mutex_unlock(&mutex)==0);observed=1;
}
static int lazy_fast_path(void) {
    reset();CHECK(pthread_mutex_lock(&mutex)==0);CHECK(!root.task.id && !admissions);
    CHECK(pthread_mutex_trylock(&mutex)==EBUSY);CHECK(pthread_mutex_unlock(&mutex)==0);
    CHECK(pthread_mutex_destroy(&mutex)==0);CHECK(source_errno==37);return 0;
}
static int recursive_errorcheck_and_identity(void) {
    reset();pthread_mutexattr_t attr;uint32_t type=PTHREAD_MUTEX_RECURSIVE;memcpy(&attr,&type,4);
    CHECK(pthread_mutex_init(&mutex,&attr)==0);
    CHECK(pthread_mutex_lock(&mutex)==0 && pthread_mutex_lock(&mutex)==0);
    active=&child;CHECK(pthread_mutex_unlock(&mutex)==EPERM);active=&root;
    CHECK(pthread_mutex_unlock(&mutex)==0 && pthread_mutex_destroy(&mutex)==EBUSY);
    CHECK(pthread_mutex_unlock(&mutex)==0 && pthread_mutex_destroy(&mutex)==0);
    type=PTHREAD_MUTEX_ERRORCHECK;memcpy(&attr,&type,4);
    CHECK(pthread_mutex_init(&mutex,&attr)==0 && pthread_mutex_lock(&mutex)==0);
    CHECK(pthread_mutex_lock(&mutex)==EDEADLK && !admissions);
    CHECK(pthread_mutex_unlock(&mutex)==0);return 0;
}
static int refused_wait_keeps_original_lock(void) {
    reset();active=&child;CHECK(pthread_mutex_lock(&mutex)==0);active=&root;capacity=0;
    CHECK(pthread_mutex_lock(&mutex)==EAGAIN && !live && !parks && !suspends);
    CHECK(sync_mutex_read(&mutex).owner==(uint32_t)(uintptr_t)&child);
    active=&child;CHECK(pthread_mutex_unlock(&mutex)==0);return 0;
}
static int actual_queue_handoff_at_suspend_port(void) {
    reset();active=&child;CHECK(pthread_mutex_lock(&mutex)==0);active=&root;
    on_suspend=child_unlock;CHECK(pthread_mutex_lock(&mutex)==0);
    CHECK(admissions==1 && returns==1 && !live && parks==1 && wakes==1 && suspends==1 && resumes==1);
    CHECK(pthread_mutex_unlock(&mutex)==0);return 0;
}
static int notification_during_broker_park_cannot_be_lost(void) {
    reset();active=&child;CHECK(pthread_mutex_lock(&mutex)==0);active=&root;
    on_park=child_unlock;CHECK(pthread_mutex_lock(&mutex)==0);
    CHECK(parks==1 && wakes==1 && !suspends && !resumes && returns==1 && !live);
    CHECK(pthread_mutex_unlock(&mutex)==0);return 0;
}
static int condition_reacquire_uses_the_same_wait_capacity(void) {
    reset();CHECK(pthread_mutex_lock(&mutex)==0);on_suspend=child_signal_held;
    CHECK(pthread_cond_wait(&condition,&mutex)==0 && observed==1);
    CHECK(admissions==1 && returns==1 && !live && parks==2 && wakes==2 && suspends==2 && resumes==2);
    CHECK(sync_mutex_read(&mutex).owner==(uint32_t)(uintptr_t)&root);
    CHECK(pthread_mutex_unlock(&mutex)==0 && pthread_cond_destroy(&condition)==0);return 0;
}
static int condition_publishes_before_release_and_rechecks_after_park(void) {
    reset();CHECK(pthread_mutex_lock(&mutex)==0);on_park=child_signal_unlock;
    CHECK(pthread_cond_wait(&condition,&mutex)==0 && observed==1);
    CHECK(!suspends && !resumes && admissions==1 && returns==1 && !live);
    CHECK(pthread_mutex_unlock(&mutex)==0);return 0;
}
static int condition_refusal_retains_lock_and_c11_uses_public_layout(void) {
    reset();CHECK(pthread_mutex_lock(&mutex)==0);capacity=0;
    CHECK(pthread_cond_wait(&condition,&mutex)==EAGAIN && !live && !parks);
    CHECK(sync_mutex_read(&mutex).owner==(uint32_t)(uintptr_t)&root);
    CHECK(pthread_mutex_unlock(&mutex)==0);
    mtx_t value;CHECK(mtx_init(&value,mtx_recursive)==thrd_success);
    CHECK(mtx_lock(&value)==thrd_success && mtx_trylock(&value)==thrd_success);
    CHECK(mtx_unlock(&value)==thrd_success && mtx_unlock(&value)==thrd_success);
    mtx_destroy(&value);cnd_t signal;CHECK(cnd_init(&signal)==thrd_success);
    CHECK(cnd_signal(&signal)==thrd_success && cnd_broadcast(&signal)==thrd_success);
    cnd_destroy(&signal);CHECK(source_errno==37);return 0;
}
static void completed_child_port(void) {
    require(active==&child && live==1 && root.waiting_for==&child && child.joiner);
    struct sync_wait *wait=(struct sync_wait *)(uintptr_t)child.joiner;
    require(wait->thread==&root && !wait->linked);
    child.tls_finished=1;child.sp=child.high;sync_notify(wait);
    /* Explicit scheduling port: deferred notification cannot switch inline;
     * model the authenticated fixed epilogue before returning to the waiter.
     */
    require(active==&child && !released && !freed);child.phase=LSF_C_FRAMES_EXITED;
}
static int join_suspends_until_deferred_completion(void) {
    reset();struct lsf_c_thread *out=NULL;on_suspend=completed_child_port;
    CHECK(join((pthread_t)&child,LSF_C_PTHREAD,&out)==0 && out==&child);
    CHECK(suspends==1 && resumes==1 && parks==1 && wakes==1 && returns==1 && !live);
    CHECK(released==3 && freed==2 && child.joined && !child.joiner && !root.waiting_for);
    CHECK(!child.stack_allocation && !child.tls_allocation);return 0;
}
static int join_completion_during_park_does_not_suspend(void) {
    reset();struct lsf_c_thread *out=NULL;on_park=completed_child_port;
    CHECK(join((pthread_t)&child,LSF_C_PTHREAD,&out)==0 && out==&child);
    CHECK(!suspends && !resumes && parks==1 && wakes==1 && returns==1 && !live);
    CHECK(released==3 && freed==2);return 0;
}
static void competing_claim_port(void) { child.joiner=1234; }
static int join_rechecks_exclusive_claim_after_admission(void) {
    reset();struct lsf_c_thread *out=NULL;on_admit=competing_claim_port;
    CHECK(join((pthread_t)&child,LSF_C_PTHREAD,&out)==EINVAL && out==NULL);
    CHECK(child.joiner==1234 && !root.waiting_for && returns==1 && !live);
    CHECK(!released && !freed && !parks && !suspends);return 0;
}
static void dependency_cycle_port(void) { child.waiting_for=&root; }
static int join_rechecks_cycles_after_admission(void) {
    reset();struct lsf_c_thread *out=NULL;on_admit=dependency_cycle_port;
    CHECK(join((pthread_t)&child,LSF_C_PTHREAD,&out)==EDEADLK && out==NULL);
    CHECK(!child.joiner && !root.waiting_for && returns==1 && !live);
    CHECK(!released && !freed && !parks && !suspends);return 0;
}
static int join_wait_refusal_cannot_publish_or_release(void) {
    reset();struct lsf_c_thread *out=NULL;capacity=0;
    CHECK(join((pthread_t)&child,LSF_C_PTHREAD,&out)==EAGAIN && out==NULL);
    CHECK(!child.joiner && !root.waiting_for && !returns && !live);
    CHECK(!released && !freed && !parks && !suspends);return 0;
}
static int reference_cases(void) {
    int (*cases[])(void)={lazy_fast_path,recursive_errorcheck_and_identity,
        refused_wait_keeps_original_lock,actual_queue_handoff_at_suspend_port,
        notification_during_broker_park_cannot_be_lost,condition_reacquire_uses_the_same_wait_capacity,
        condition_publishes_before_release_and_rechecks_after_park,
        condition_refusal_retains_lock_and_c11_uses_public_layout,
        join_suspends_until_deferred_completion,join_completion_during_park_does_not_suspend,
        join_rechecks_exclusive_claim_after_admission,join_rechecks_cycles_after_admission,
        join_wait_refusal_cannot_publish_or_release};
    for (unsigned index=0;index<sizeof(cases)/sizeof(cases[0]);++index) {
        case_index=index+1;if (cases[index]()) return (int)index+1;
    }
    printf("PASS:13 serialized production-source cases; no engine/ledger qualification\n");return 0;
}
void lsf_test_entry(void) { ExitProcess((unsigned)reference_cases()); }
