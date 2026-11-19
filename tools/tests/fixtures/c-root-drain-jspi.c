#if defined(LSF_C_BARRIER_BASELINE)
/* Unmodified pinned libc stubs: no errno shim, provider or runtime is linked. */
#include <pthread.h>
#include <stddef.h>
#include <stdint.h>
static pthread_barrier_t baseline_one,baseline_two;
__attribute__((export_name("baseline_single"))) int baseline_single(void) {
    int result=pthread_barrier_init(&baseline_one,NULL,1);
    if (result) return result;
    return pthread_barrier_wait(&baseline_one)==PTHREAD_BARRIER_SERIAL_THREAD;
}
__attribute__((export_name("baseline_multiple"))) int baseline_multiple(void) {
    int result=pthread_barrier_init(&baseline_two,NULL,2);
    if (result) return result;
    return pthread_barrier_wait(&baseline_two);
}
__attribute__((export_name("baseline_attributes"))) int baseline_attributes(void) {
    pthread_barrierattr_t attr;uint32_t flags;
    if (pthread_barrierattr_init(&attr)) return 0;
    __builtin_memcpy(&flags,&attr,sizeof(flags));if (flags) return 0;
    if (pthread_barrierattr_setpshared(&attr,PTHREAD_PROCESS_SHARED)) return 0;
    __builtin_memcpy(&flags,&attr,sizeof(flags));return flags==UINT32_C(0x80000000);
}
#elif defined(LSF_C_BARRIER_CLIENT)
/* Ordinary caller compiled against pinned pthread.h and SDK source defines. */
#include <pthread.h>
#include <stddef.h>
int barrier_client(pthread_barrier_t *object) {
    int result=pthread_barrier_init(object,NULL,2);
    result+=pthread_barrier_wait(object);result+=pthread_barrier_destroy(object);
    return result;
}
#elif defined(LSF_C_SEMAPHORE_CLIENT)
/* Ordinary caller compiled with the real pinned semaphore.h and SDK defines. */
#include <semaphore.h>
int semaphore_client(sem_t *object,const struct timespec *deadline,int *value) {
    int result=sem_init(object,0,1);
    result+=sem_getvalue(object,value);result+=sem_trywait(object);result+=sem_wait(object);
    result+=sem_post(object);result+=sem_timedwait(object,deadline);result+=sem_destroy(object);
    return result;
}
#elif defined(LSF_C_CREATE_CONTROL)
/* Actual create/discard source with explicit finite broker and JSPI ports.
 * No libc errno getter, canonical runtime or real activation ledger runs. */
#include <errno.h>
#include <pthread.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include "thread-abi.h"

#define RECORD_LIMIT 32u
#define STACK_BYTES 65536u
#define TEMPLATE_LIMIT (1024u*1024u)
static struct lsf_c_thread root,callers[31];
static unsigned char template_bytes[16];
__attribute__((aligned(16))) static unsigned char heap[262144];
static unsigned heap_used,allocations,frees,allocation_attempts;
static unsigned token_serial,live_tokens,settled_tokens,admit_calls;
static unsigned fail_stage,fail_kind,pause_kind,pause_settle;
static void *owned[8];

__attribute__((import_module("test"),import_name("context"))) uint32_t test_context(void);
__attribute__((import_module("test"),import_name("hold-admission"))) void test_hold_admission(void);
__attribute__((import_module("test"),import_name("hold-settle"))) void test_hold_settle(void);
static void require(int value) { if (!value) __builtin_trap(); }
static int token_live(struct lsf_c_token value) { return value.generation && value.id; }
static struct lsf_c_thread *current(void) { return (struct lsf_c_thread *)(uintptr_t)test_context(); }
static int runtime_error(unsigned value) { return value==2 ? EAGAIN : EINVAL; }

void *memset(void *destination,int value,size_t size) {
    unsigned char *out=destination;for(size_t i=0;i<size;++i)out[i]=(unsigned char)value;return destination;
}
void *memcpy(void *destination,const void *source,size_t size) {
    unsigned char *out=destination;const unsigned char *in=source;
    for(size_t i=0;i<size;++i)out[i]=in[i];return destination;
}
void *aligned_alloc(size_t alignment,size_t size) {
    require(alignment==16 && size%16==0);++allocation_attempts;
    if (fail_stage==10+allocation_attempts) return NULL;
    require(heap_used<=sizeof(heap) && size<=sizeof(heap)-heap_used && allocations<8);
    void *result=heap+heap_used;heap_used+=(unsigned)size;owned[allocations++]=result;return result;
}
void free(void *pointer) {
    if (!pointer) return;
    for(unsigned index=0;index<allocations;++index) if(owned[index]==pointer) {
        owned[index]=NULL;++frees;return;
    }
    __builtin_trap();
}
static int ensure_root_owners(struct lsf_c_thread *value) {
    require(value==&root && token_live(value->task));return fail_stage==1 ? EAGAIN : 0;
}
static int ensure_template(struct lsf_c_thread *value) {
    require(value==&root && value->initial_template);return fail_stage==2 ? ENOMEM : 0;
}
static int acquire(unsigned kind,const struct lsf_c_token *parent,struct lsf_c_token *out) {
    require(parent && token_live(*parent));++admit_calls;
    if (current()==&callers[0] && pause_kind==kind) { pause_kind=UINT32_MAX;test_hold_admission(); }
    if (fail_kind==kind) return EAGAIN;
    ++live_tokens;*out=(struct lsf_c_token){1,++token_serial+100};return 0;
}
static void settle(struct lsf_c_token *token) {
    if (!token_live(*token)) return;
    if (current()==&callers[0] && pause_settle) { pause_settle=0;test_hold_settle(); }
    require(live_tokens);--live_tokens;++settled_tokens;*token=(struct lsf_c_token){0};
}
#include "c-create-reference-body.h"

static void *start(void *argument) { return argument; }
void setup_create(unsigned existing,unsigned stage,unsigned kind,unsigned pause,unsigned settle_pause) {
    require(existing>=2 && existing<=31);
    memset(&root,0,sizeof(root));memset(callers,0,sizeof(callers));memset(owned,0,sizeof(owned));
    heap_used=allocations=frees=allocation_attempts=token_serial=live_tokens=settled_tokens=admit_calls=0;
    fail_stage=stage;fail_kind=kind;pause_kind=pause;pause_settle=settle_pause;
    root.root=&root;root.phase=LSF_C_RUNNING;root.api=LSF_C_ROOT;root.task=(struct lsf_c_token){1,1};
    root.tls_bytes=sizeof(template_bytes);root.initial_template=template_bytes;root.started_count=existing;
    root.next=&callers[0];
    for(unsigned i=0;i<existing;++i) {
        callers[i].root=&root;callers[i].phase=LSF_C_RUNNING;callers[i].canonical_id=i+1;
        callers[i].task=(struct lsf_c_token){1,i+2};callers[i].next=i+1<existing?&callers[i+1]:NULL;
    }
}
uint32_t caller_pointer(unsigned index) { require(index<2);return (uint32_t)(uintptr_t)&callers[index]; }
int start_create(void) { struct lsf_c_thread *out=NULL;return create(&out,start,NULL,NULL,LSF_C_PTHREAD); }
void close_create_root(void) { root.closing=1; }
unsigned create_count(void) { return root.started_count; }
unsigned create_list_count(void) {
    unsigned total=0;for(struct lsf_c_thread *thread=root.next;thread;thread=thread->next) {
        require(++total<=33);
    }
    return total;
}
unsigned create_live(void) { return live_tokens; }
unsigned create_settled(void) { return settled_tokens; }
unsigned create_admissions(void) { return admit_calls; }
unsigned create_allocations(void) { return allocations; }
unsigned create_frees(void) { return frees; }
int create_eagain(void) { return EAGAIN; }
int create_enomem(void) { return ENOMEM; }

#else
/* Actual maintained C join/drain bodies with explicit JSPI scheduler and
 * broker doubles. This is not an engine, ledger or signed guest result. */
#include <stdint.h>
#include <stddef.h>
#include "c-sync-reference-abi.h"
#include "thread-abi.h"
struct timespec { int64_t tv_sec; long tv_nsec; };
#define RECORD_LIMIT 32u
static int fake_errno;
#undef errno
#define errno fake_errno
static struct lsf_c_thread root,first,second;
static unsigned live,peak,admitted,settled,released,freed,parked,woken,tls_finished;
static unsigned pause_admission,pause_park,hold_first,single_child,refuse_wait;
static unsigned allocations[4];

__attribute__((import_module("test"),import_name("context"))) uint32_t test_context(void);
__attribute__((import_module("test"),import_name("hold"))) void test_hold(void);
__attribute__((import_module("test"),import_name("admit"))) void test_admit(void);
__attribute__((import_module("test"),import_name("park"))) void test_park(void);
static void *memcpy(void *d,const void *s,size_t n) {
    unsigned char *out=d;const unsigned char *in=s;
    for(size_t i=0;i<n;++i)out[i]=in[i];return d;
}
#if defined(LSF_C_RWLOCKS) && LSF_C_RWLOCKS
static void *memset(void *d,int value,size_t n) {
    unsigned char *out=d;for(size_t i=0;i<n;++i)out[i]=(unsigned char)value;return d;
}
#endif
static void require(int value) { if(!value)__builtin_trap(); }
static struct lsf_c_thread *current(void) { return (struct lsf_c_thread *)(uintptr_t)test_context(); }
static int ensure_root_owners(struct lsf_c_thread *value) {
    if(!value->task.id)value->task=(struct lsf_c_token){1,50};return 0;
}
static int acquire(unsigned kind,const struct lsf_c_token *parent,struct lsf_c_token *out) {
    require(kind==LSF_C_WAIT && parent && parent->id && live<2);
    if(refuse_wait)return EAGAIN;
    ++admitted;++live;if(live>peak)peak=live;*out=(struct lsf_c_token){1,100+admitted};
    if((current()==&root && pause_admission==1) || (current()==&first && pause_admission==2)) {
        pause_admission=0;test_admit();
    }
    return 0;
}
static void settle(struct lsf_c_token *owner) {
    require(owner->id);
    if(owner->id>=1000)++released;
    else { require(live);--live;++settled; }
    *owner=(struct lsf_c_token){0};
}
static void free(void *value) { require(value!=NULL);++freed; }
static void park(struct lsf_c_token value) {
    require(value.id);++parked;
    if(current()==&root && pause_park) { pause_park=0;test_park(); }
}
static void wake(struct lsf_c_token value) { require(value.id);++woken; }
#include "synchronization.c"
int lsf_c_tls_finish(void) { ++tls_finished;return 0; }
#include "c-root-drain-reference-body.h"

static void *finish_immediately(void *argument) { return argument; }
static void *join_second(void *argument) {
    struct lsf_c_thread *joined=NULL;(void)argument;
    require(join((pthread_t)&second,LSF_C_PTHREAD,&joined)==0 && joined==&second);
    if(hold_first)test_hold();
    return NULL;
}
void setup(unsigned scenario) {
    root=(struct lsf_c_thread){.low=0x100000,.high=0x110000,.phase=LSF_C_RUNNING,
        .canonical_id=10,.task={1,50},.api=LSF_C_ROOT};
    first=(struct lsf_c_thread){.low=0x200000,.high=0x210000,.sp=0x210000,
        .phase=LSF_C_RUNNING,.canonical_id=11,.creation_started=1,.task={1,1001},
        .context_owner={1,1002},.result_owner={1,1003},.api=LSF_C_PTHREAD,
        .stack_allocation=&allocations[0],.tls_allocation=&allocations[1]};
    second=(struct lsf_c_thread){.low=0x300000,.high=0x310000,.sp=0x310000,
        .phase=LSF_C_RUNNING,.canonical_id=12,.creation_started=1,.task={1,1004},
        .context_owner={1,1005},.result_owner={1,1006},.api=LSF_C_PTHREAD,
        .stack_allocation=&allocations[2],.tls_allocation=&allocations[3]};
    root.root=&root;first.root=&root;second.root=&root;
    single_child=scenario!=0;root.next=single_child?&first:&second;second.next=&first;
    first.start.pthread=single_child?finish_immediately:join_second;
    second.start.pthread=finish_immediately;
    live=peak=admitted=settled=released=freed=parked=woken=tls_finished=0;
    fake_errno=37;pause_admission=scenario==1;pause_park=scenario==2;hold_first=!single_child;refuse_wait=0;
}
uint32_t root_pointer(void) { return (uint32_t)(uintptr_t)&root; }
uint32_t first_pointer(void) { return (uint32_t)(uintptr_t)&first; }
uint32_t second_pointer(void) { return (uint32_t)(uintptr_t)&second; }
void start_root(void) { __lsf_c_root_finish(&root); }
void start_first(void) { __lsf_c_thread_body(&first);first.phase=LSF_C_FRAMES_EXITED; }
void start_second(void) { __lsf_c_thread_body(&second);second.phase=LSF_C_FRAMES_EXITED; }
unsigned read_live(void) { return live; }
unsigned read_peak(void) { return peak; }
unsigned read_admitted(void) { return admitted; }
unsigned read_settled(void) { return settled; }
unsigned read_released(void) { return released; }
unsigned read_freed(void) { return freed; }
unsigned read_parked(void) { return parked; }
unsigned read_woken(void) { return woken; }
unsigned read_tls(void) { return tls_finished; }
unsigned read_first_phase(void) { return first.phase; }
unsigned read_second_phase(void) { return second.phase; }
unsigned read_second_claimed(void) { return second.joiner!=0; }
unsigned read_second_joined(void) { return second.joined; }
unsigned read_root_observer(void) { return root.drain_wait!=NULL; }
#if defined(LSF_C_RWLOCKS) && LSF_C_RWLOCKS
static pthread_rwlock_t test_rwlock;
static pthread_rwlockattr_t test_rwattr;
void rw_setup(void) { memset(&test_rwlock,0,sizeof(test_rwlock));memset(&test_rwattr,0,sizeof(test_rwattr)); }
void rw_set_shared(void) { uint32_t flags[2]={1,0};memcpy(&test_rwattr,flags,sizeof(flags)); }
void rw_set_reader_limit(void) { sync_rw_write(&test_rwlock,(struct sync_rwlock){.readers=UINT32_MAX}); }
void rw_refuse_wait(unsigned value) { refuse_wait=value; }
void rw_pause_admission(void) { pause_admission=2; }
int rw_init_default(void) { return pthread_rwlock_init(&test_rwlock,&test_rwattr); }
int rw_destroy(void) { return pthread_rwlock_destroy(&test_rwlock); }
int rw_read(void) { return pthread_rwlock_rdlock(&test_rwlock); }
int rw_write(void) { return pthread_rwlock_wrlock(&test_rwlock); }
int rw_tryread(void) { return pthread_rwlock_tryrdlock(&test_rwlock); }
int rw_trywrite(void) { return pthread_rwlock_trywrlock(&test_rwlock); }
int rw_unlock(void) { return pthread_rwlock_unlock(&test_rwlock); }
static const struct timespec rw_invalid_deadline={0,1000000000L};
int rw_timedread(void) { return pthread_rwlock_timedrdlock(&test_rwlock,&rw_invalid_deadline); }
int rw_timedwrite(void) { return pthread_rwlock_timedwrlock(&test_rwlock,&rw_invalid_deadline); }
int rw_errno(void) { return fake_errno; }
int rw_busy(void) { return EBUSY; }
int rw_again(void) { return EAGAIN; }
int rw_notsup(void) { return ENOTSUP; }
int rw_perm(void) { return EPERM; }
int rw_deadlock(void) { return EDEADLK; }
#endif
#if defined(LSF_C_SEMAPHORES) && LSF_C_SEMAPHORES
static sem_t test_semaphore;
int ss_setup(unsigned count) { memset(&test_semaphore,0,sizeof(test_semaphore));return sem_init(&test_semaphore,0,count); }
int ss_shared(void) { return sem_init(&test_semaphore,1,0); }
int ss_invalid(void) { return sem_init(&test_semaphore,0,UINT32_MAX); }
int ss_destroy(void) { return sem_destroy(&test_semaphore); }
int ss_getvalue(void) { int value=-1;return sem_getvalue(&test_semaphore,&value)==0?value:-1; }
int ss_wait(void) { return sem_wait(&test_semaphore); }
int ss_trywait(void) { return sem_trywait(&test_semaphore); }
int ss_post(void) { return sem_post(&test_semaphore); }
int ss_timedwait(void) { return sem_timedwait(&test_semaphore,NULL); }
void ss_pause_admission(void) { pause_admission=2; }
void ss_refuse_wait(unsigned value) { refuse_wait=value; }
int ss_errno(void) { return fake_errno; }
int ss_eagain(void) { return EAGAIN; }
int ss_ebusy(void) { return EBUSY; }
int ss_einval(void) { return EINVAL; }
int ss_overflow(void) { return EOVERFLOW; }
int ss_notsup(void) { return ENOTSUP; }
int ss_intmax(void) { return INT_MAX; }
#endif
#if defined(LSF_C_BARRIERS) && LSF_C_BARRIERS
static pthread_barrier_t test_barrier;
int bar_setup(unsigned count) { memset(&test_barrier,0,sizeof(test_barrier));return pthread_barrier_init(&test_barrier,NULL,count); }
int bar_shared(void) {
    pthread_barrierattr_t attr;uint32_t flags=UINT32_C(0x80000000);memcpy(&attr,&flags,sizeof(flags));
    return pthread_barrier_init(&test_barrier,&attr,2);
}
int bar_invalid(void) { return pthread_barrier_init(&test_barrier,NULL,0); }
int bar_above(void) { return pthread_barrier_init(&test_barrier,NULL,RECORD_LIMIT+2u); }
int bar_destroy(void) { return pthread_barrier_destroy(&test_barrier); }
int bar_wait(void) { return pthread_barrier_wait(&test_barrier); }
void bar_pause_admission(void) { pause_admission=2; }
void bar_refuse_wait(unsigned value) { refuse_wait=value; }
int bar_errno(void) { return fake_errno; }
int bar_serial(void) { return PTHREAD_BARRIER_SERIAL_THREAD; }
int bar_eagain(void) { return EAGAIN; }
int bar_ebusy(void) { return EBUSY; }
int bar_einval(void) { return EINVAL; }
int bar_notsup(void) { return ENOTSUP; }
#endif
#endif
