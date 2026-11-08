/* Actual maintained C join/drain bodies with explicit JSPI scheduler and
 * broker doubles. This is not an engine, ledger or signed guest result. */
#include <stdint.h>
#include <stddef.h>
#include "c-sync-reference-abi.h"
#include "thread-abi.h"
struct timespec;
#define RECORD_LIMIT 32u
static int fake_errno;
#undef errno
#define errno fake_errno
static struct lsf_c_thread root,first,second;
static unsigned live,peak,admitted,settled,released,freed,parked,woken,tls_finished;
static unsigned pause_admission,pause_park,hold_first,single_child;
static unsigned allocations[4];

__attribute__((import_module("test"),import_name("context"))) uint32_t test_context(void);
__attribute__((import_module("test"),import_name("hold"))) void test_hold(void);
__attribute__((import_module("test"),import_name("admit"))) void test_admit(void);
__attribute__((import_module("test"),import_name("park"))) void test_park(void);
static void *memcpy(void *d,const void *s,size_t n) {
    unsigned char *out=d;const unsigned char *in=s;
    for(size_t i=0;i<n;++i)out[i]=in[i];return d;
}
static void require(int value) { if(!value)__builtin_trap(); }
static struct lsf_c_thread *current(void) { return (struct lsf_c_thread *)(uintptr_t)test_context(); }
static int ensure_root_owners(struct lsf_c_thread *value) {
    if(!value->task.id)value->task=(struct lsf_c_token){1,50};return 0;
}
static int acquire(unsigned kind,const struct lsf_c_token *parent,struct lsf_c_token *out) {
    require(kind==LSF_C_WAIT && parent && parent->id && live<2);
    ++admitted;++live;if(live>peak)peak=live;*out=(struct lsf_c_token){1,100+admitted};
    if(current()==&root && pause_admission) { pause_admission=0;test_admit(); }
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
    fake_errno=37;pause_admission=scenario==1;pause_park=scenario==2;hold_first=!single_child;
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
