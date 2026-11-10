/* Serialized C source controls. Clock, broker and scheduler are explicit
 * doubles; these cases are not a signed guest or original-ledger run. */
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <pthread.h>
#include <stdint.h>
#include <string.h>
#include <threads.h>
#include <time.h>
#include "thread-abi.h"

void *memcpy(void *out,const void *in,size_t n) {
    unsigned char *d=out;const unsigned char *s=in;
    for (size_t i=0;i<n;++i) d[i]=s[i];return out;
}
void *memset(void *out,int value,size_t n) {
    unsigned char *d=out;for (size_t i=0;i<n;++i) d[i]=(unsigned char)value;return out;
}
struct __clockid { uint32_t id; };
const struct __clockid _CLOCK_REALTIME={0},_CLOCK_MONOTONIC={1};
static struct timespec sample;
static unsigned clock_calls,clock_failure;
static int source_errno;
#undef errno
#define errno source_errno
int clock_gettime(clockid_t clock,struct timespec *out) {
    if (clock!=CLOCK_REALTIME && clock!=CLOCK_MONOTONIC) __builtin_trap();
    ++clock_calls;if (clock_failure) { source_errno=EIO;return -1; }
    *out=sample;return 0;
}

#define RECORD_LIMIT 32u
struct token_result { uint8_t tag,pad[7];union { struct lsf_c_token token;uint8_t error; } value; };
struct unit_result { uint8_t tag,error; };
static struct lsf_c_thread root,child,*active;
static unsigned admissions,settlements,parks,wakes,suspends,resumes,timers,stops;
static unsigned next_error,global_cancel,next_calls,wake_attempts,refuse_wait,refuse_timer;
static uint64_t admitted_nanos;
static void (*on_suspend)(void),(*on_timer_next)(void);
static void require(int value) { if (!value) __builtin_trap(); }
static int token_live(struct lsf_c_token value) { return value.generation && value.id; }
static struct lsf_c_thread *current(void) { return active; }
static int ensure_root_owners(struct lsf_c_thread *value) {
    if (!value->task.id) value->task=(struct lsf_c_token){1,7};return 0;
}
static int acquire(unsigned kind,const struct lsf_c_token *parent,struct lsf_c_token *out) {
    require(kind==LSF_C_WAIT && parent && parent->id);++admissions;
    if (refuse_wait) return EAGAIN;
    *out=(struct lsf_c_token){1,11};return 0;
}
static void settle(struct lsf_c_token *token) {
    require(token->generation==1 && token->id==11);++settlements;*token=(struct lsf_c_token){0};
}
static void park(struct lsf_c_token token) { require(token.id);++parks; }
static void wake(struct lsf_c_token token) { ++wake_attempts;require(token.id && !global_cancel);++wakes; }
static int runtime_error(unsigned value) { if (value==2) return EAGAIN;__builtin_trap(); }
#include "synchronization.c"

uint32_t __lsf_c_sync_suspend(void) {
    ++suspends;require(on_suspend!=NULL);void (*callback)(void)=on_suspend;on_suspend=NULL;
    struct lsf_c_thread *saved=active;active=&child;callback();active=saved;return 0;
}
void __lsf_c_sync_resume_later(uint32_t id) { require(id==root.canonical_id);++resumes; }
void sync_host_timer_start(uint64_t delay,uint32_t has_period,uint64_t period,
                           uint32_t has_parent,uint64_t generation,uint64_t id,
                           struct token_result *out) {
    require(!has_period && !period && has_parent && generation==1 && id==11);
    ++timers;admitted_nanos=delay;
    if (refuse_timer) { out->tag=1;out->value.error=2;return; }
    out->tag=0;out->value.token=(struct lsf_c_token){1,13};
}
void sync_host_timer_next(uint64_t generation,uint64_t id,struct sync_timer_result *out) {
    require(generation==1 && id==13);++next_calls;
    if (on_timer_next) {
        void (*callback)(void)=on_timer_next;on_timer_next=NULL;
        struct lsf_c_thread *saved=active;active=&child;callback();active=saved;
    }
    if (next_error) { out->tag=1;out->value.error=next_error; }
    else { out->tag=0;out->value.skipped=0; }
}
void sync_host_timer_stop(uint64_t generation,uint64_t id,struct unit_result *out) {
    require(generation==1 && id==13);++stops;out->tag=0;
}

static pthread_mutex_t mutex;
static pthread_cond_t cond;
static mtx_t c11_mutex;
static cnd_t c11_cond;
static struct sync_wait queued;
#define CHECK(value) do { if (!(value)) return __LINE__; } while (0)
static void reset(void) {
    root=(struct lsf_c_thread){.canonical_id=11,.phase=LSF_C_RUNNING};root.root=&root;
    child=(struct lsf_c_thread){.canonical_id=12,.phase=LSF_C_RUNNING,.root=&root,.task={1,9}};
    active=&root;sample=(struct timespec){2000000000,500000000};
    admissions=settlements=parks=wakes=suspends=resumes=timers=stops=0;
    admitted_nanos=0;clock_calls=clock_failure=0;source_errno=37;
    next_error=global_cancel=next_calls=wake_attempts=refuse_wait=refuse_timer=0;on_suspend=on_timer_next=NULL;
    memset(&mutex,0,sizeof(mutex));memset(&cond,0,sizeof(cond));
    memset(&c11_mutex,0,sizeof(c11_mutex));memset(&c11_cond,0,sizeof(c11_cond));
    memset(&queued,0,sizeof(queued));
}
static void child_unlock(void) { require(pthread_mutex_unlock(&mutex)==0); }
static void child_unlock_c11(void) { require(mtx_unlock(&c11_mutex)==thrd_success); }
static void child_unlock_during_reacquire(void) {
    require(admissions==1 && settlements==0 && timers==1 && stops==1);child_unlock();
}
static void child_unlock_c11_during_reacquire(void) {
    require(admissions==1 && settlements==0 && timers==1 && stops==1);child_unlock_c11();
}
static void child_signal(void) { require(pthread_cond_signal(&cond)==0); }
static void child_unlock_and_cancel(void) { child_unlock();global_cancel=1; }
static void cancel_before_wake(void) { global_cancel=1; }
static void queue_child(void *object) {
    queued=(struct sync_wait){.thread=&child,.linked=1};
    struct sync_mutex value=sync_mutex_read(object);
    value.head=value.tail=&queued;value.waiters=1;sync_mutex_write(object,value);
}

__attribute__((export_name("mutex_fast"))) int mutex_fast(void) {
    reset();const struct timespec bad={-1,-1};
    CHECK(pthread_mutex_timedlock(&mutex,&bad)==0);
    CHECK(clock_calls==0 && admissions==0 && timers==0 && source_errno==37);
    CHECK(pthread_mutex_unlock(&mutex)==0);return 0;
}
__attribute__((export_name("mutex_expired"))) int mutex_expired(void) {
    reset();active=&child;CHECK(pthread_mutex_lock(&mutex)==0);active=&root;
    const struct timespec expired={INT64_MIN,999999999};
    CHECK(pthread_mutex_timedlock(&mutex,&expired)==ETIMEDOUT);
    CHECK(clock_calls==1 && admissions==0 && timers==0 && source_errno==37);
    CHECK(sync_mutex_read(&mutex).owner==(uint32_t)(uintptr_t)&child);
    return 0;
}
__attribute__((export_name("mutex_invalid"))) int mutex_invalid(void) {
    reset();active=&child;CHECK(pthread_mutex_lock(&mutex)==0);active=&root;
    struct timespec bad={-1,-1};
    CHECK(pthread_mutex_timedlock(&mutex,&bad)==EINVAL);
    bad.tv_nsec=1000000000;
    CHECK(pthread_mutex_timedlock(&mutex,&bad)==EINVAL);
    CHECK(clock_calls==0 && admissions==0 && timers==0 && source_errno==37);return 0;
}
__attribute__((export_name("condition_expired"))) int condition_expired(void) {
    reset();CHECK(pthread_mutex_lock(&mutex)==0);queue_child(&mutex);on_suspend=child_unlock;
    const struct timespec expired={-1,999999999};
    CHECK(pthread_cond_timedwait(&cond,&mutex,&expired)==ETIMEDOUT);
    CHECK(queued.notified && !queued.linked && admissions==1 && settlements==1 && !timers);
    CHECK(parks==1 && wakes==1 && suspends==1 && resumes==1 && source_errno==37);
    CHECK(sync_mutex_read(&mutex).owner==(uint32_t)(uintptr_t)&root);
    CHECK(pthread_mutex_unlock(&mutex)==0);return 0;
}
__attribute__((export_name("condition_invalid"))) int condition_invalid(void) {
    reset();CHECK(pthread_mutex_lock(&mutex)==0);queue_child(&mutex);
    struct timespec bad={-1,-1};
    CHECK(pthread_cond_timedwait(&cond,&mutex,&bad)==EINVAL);bad.tv_nsec=1000000000;
    CHECK(pthread_cond_timedwait(&cond,&mutex,&bad)==EINVAL);
    CHECK(!queued.notified && queued.linked && admissions==0 && clock_calls==0 && timers==0);
    CHECK(sync_mutex_read(&mutex).owner==(uint32_t)(uintptr_t)&root && source_errno==37);
    return 0;
}
__attribute__((export_name("future_relative"))) int future_relative(void) {
    reset();active=&child;CHECK(pthread_mutex_lock(&mutex)==0);active=&root;
    const struct timespec future={18446744074LL,250000000};
    CHECK(pthread_mutex_timedlock(&mutex,&future)==ETIMEDOUT);
    CHECK(admitted_nanos==UINT64_C(16446744073750000000));
    CHECK(admissions==1 && settlements==1 && timers==1 && stops==1 && parks==1 && wakes==1);
    CHECK(sync_mutex_read(&mutex).owner==(uint32_t)(uintptr_t)&child && source_errno==37);return 0;
}
__attribute__((export_name("future_overflow"))) int future_overflow(void) {
    reset();active=&child;CHECK(pthread_mutex_lock(&mutex)==0);active=&root;
    const struct timespec future={INT64_MAX,999999999};
    CHECK(pthread_mutex_timedlock(&mutex,&future)==EOVERFLOW);
    CHECK(clock_calls==1 && admissions==0 && timers==0 && source_errno==37);return 0;
}
__attribute__((export_name("clock_failure"))) int clock_failure_case(void) {
    reset();active=&child;CHECK(pthread_mutex_lock(&mutex)==0);active=&root;clock_failure=1;
    const struct timespec expired={-1,0};
    CHECK(pthread_mutex_timedlock(&mutex,&expired)==EIO);
    CHECK(clock_calls==1 && admissions==0 && timers==0 && source_errno==37);return 0;
}
__attribute__((export_name("c11_expired"))) int c11_expired(void) {
    reset();CHECK(mtx_init(&c11_mutex,mtx_timed)==thrd_success);
    active=&child;CHECK(mtx_lock(&c11_mutex)==thrd_success);active=&root;
    const struct timespec expired={-1,0};
    CHECK(mtx_timedlock(&c11_mutex,&expired)==thrd_timedout);
    CHECK(!admissions && !timers && source_errno==37);
    active=&child;CHECK(mtx_unlock(&c11_mutex)==thrd_success);active=&root;
    CHECK(mtx_lock(&c11_mutex)==thrd_success);queue_child(&c11_mutex);on_suspend=child_unlock_c11;
    CHECK(cnd_init(&c11_cond)==thrd_success);
    CHECK(cnd_timedwait(&c11_cond,&c11_mutex,&expired)==thrd_timedout);
    CHECK(queued.notified && !queued.linked && admissions==1 && settlements==1 && !timers);
    CHECK(parks==1 && wakes==1 && suspends==1 && resumes==1 && source_errno==37);
    CHECK(sync_mutex_read(&c11_mutex).owner==(uint32_t)(uintptr_t)&root);
    CHECK(mtx_unlock(&c11_mutex)==thrd_success);return 0;
}
__attribute__((export_name("duration_boundaries"))) int duration_boundaries(void) {
    reset();uint64_t nanos=17;
    struct timespec deadline={20446744074LL,209551615};
    CHECK(sync_remaining(0,&deadline,&nanos)==0 && nanos==UINT64_MAX);
    ++deadline.tv_nsec;
    CHECK(sync_remaining(0,&deadline,&nanos)==EOVERFLOW);
    sample=(struct timespec){5,900000000};deadline=(struct timespec){6,100000000};
    CHECK(sync_remaining(1,&deadline,&nanos)==0 && nanos==200000000);
    deadline=(struct timespec){5,900000000};
    CHECK(sync_remaining(0,&deadline,&nanos)==0 && nanos==0);
    deadline.tv_nsec=899999999;
    CHECK(sync_remaining(0,&deadline,&nanos)==0 && nanos==0);
    deadline=(struct timespec){-1,0};
    CHECK(sync_duration(&deadline,&nanos)==EINVAL);return 0;
}

/* ResourceExhausted is WIT error ordinal 2 from the actual timer-next host.
 * Its additional physical Wait can be refused after this source has admitted
 * its own Wait and Timer. The ports below model that result, not the ledger. */
__attribute__((export_name("mutex_next_refused"))) int mutex_next_refused(void) {
    reset();active=&child;CHECK(pthread_mutex_lock(&mutex)==0);active=&root;next_error=2;
    const struct timespec future={2000000001,500000000};
    CHECK(pthread_mutex_timedlock(&mutex,&future)==EAGAIN);
    struct sync_mutex value=sync_mutex_read(&mutex);
    CHECK(value.owner==(uint32_t)(uintptr_t)&child && !value.head && !value.tail && !value.waiters);
    CHECK(admissions==1 && settlements==1 && timers==1 && stops==1 && parks==1 && wakes==1);
    active=&child;CHECK(pthread_mutex_unlock(&mutex)==0);active=&root;
    CHECK(pthread_mutex_trylock(&mutex)==0 && pthread_mutex_unlock(&mutex)==0);return 0;
}
__attribute__((export_name("condition_next_refused"))) int condition_next_refused(void) {
    reset();CHECK(pthread_mutex_lock(&mutex)==0);queue_child(&mutex);
    on_suspend=child_unlock_during_reacquire;next_error=2;
    const struct timespec future={2000000001,500000000};
    CHECK(pthread_cond_timedwait(&cond,&mutex,&future)==EAGAIN);
    struct sync_cond value=sync_cond_read(&cond);
    CHECK(!value.head && !value.tail && !value.mutex && !value.waiters);
    CHECK(sync_mutex_read(&mutex).owner==(uint32_t)(uintptr_t)&root && queued.notified);
    CHECK(admissions==1 && settlements==1 && timers==1 && stops==1 && parks==2 && wakes==2);
    CHECK(suspends==1 && resumes==1 && pthread_mutex_unlock(&mutex)==0);return 0;
}
__attribute__((export_name("sleep_next_refused"))) int sleep_next_refused(void) {
    reset();next_error=2;const struct timespec duration={1,0};struct timespec remaining={8,9};
    CHECK(thrd_sleep(&duration,&remaining)==-2 && remaining.tv_sec==8 && remaining.tv_nsec==9);
    CHECK(admissions==1 && settlements==1 && timers==1 && stops==1 && parks==1 && wakes==1);
    return 0;
}
__attribute__((export_name("c11_next_refused"))) int c11_next_refused(void) {
    reset();CHECK(mtx_init(&c11_mutex,mtx_timed)==thrd_success);
    active=&child;CHECK(mtx_lock(&c11_mutex)==thrd_success);active=&root;next_error=2;
    const struct timespec future={2000000001,500000000};
    CHECK(mtx_timedlock(&c11_mutex,&future)==thrd_error);
    struct sync_mutex value=sync_mutex_read(&c11_mutex);
    CHECK(value.owner==(uint32_t)(uintptr_t)&child && !value.head && !value.waiters);
    CHECK(admissions==1 && settlements==1 && timers==1 && stops==1 && parks==1 && wakes==1);
    return 0;
}
__attribute__((export_name("c11_condition_next_refused"))) int c11_condition_next_refused(void) {
    reset();CHECK(mtx_init(&c11_mutex,mtx_timed)==thrd_success);
    CHECK(cnd_init(&c11_cond)==thrd_success && mtx_lock(&c11_mutex)==thrd_success);
    queue_child(&c11_mutex);on_suspend=child_unlock_c11_during_reacquire;next_error=2;
    const struct timespec future={2000000001,500000000};
    CHECK(cnd_timedwait(&c11_cond,&c11_mutex,&future)==thrd_error);
    struct sync_cond value=sync_cond_read(&c11_cond);
    CHECK(!value.head && !value.tail && !value.mutex && !value.waiters);
    CHECK(sync_mutex_read(&c11_mutex).owner==(uint32_t)(uintptr_t)&root && queued.notified);
    CHECK(admissions==1 && settlements==1 && timers==1 && stops==1 && parks==2 && wakes==2);
    CHECK(suspends==1 && resumes==1 && mtx_unlock(&c11_mutex)==thrd_success);return 0;
}
__attribute__((export_name("mutex_notification_during_refusal"))) int mutex_notification_during_refusal(void) {
    reset();active=&child;CHECK(pthread_mutex_lock(&mutex)==0);active=&root;
    next_error=2;on_timer_next=child_unlock;
    const struct timespec future={2000000001,500000000};
    CHECK(pthread_mutex_timedlock(&mutex,&future)==0);
    struct sync_mutex value=sync_mutex_read(&mutex);
    CHECK(value.owner==(uint32_t)(uintptr_t)&root && !value.head && !value.tail && !value.waiters);
    CHECK(admissions==1 && settlements==1 && timers==1 && stops==1 && parks==1 && wakes==1);
    CHECK(pthread_mutex_unlock(&mutex)==0);return 0;
}
__attribute__((export_name("condition_notification_during_refusal"))) int condition_notification_during_refusal(void) {
    reset();CHECK(pthread_mutex_lock(&mutex)==0);next_error=2;on_timer_next=child_signal;
    const struct timespec future={2000000001,500000000};
    CHECK(pthread_cond_timedwait(&cond,&mutex,&future)==0);
    struct sync_cond value=sync_cond_read(&cond);
    CHECK(!value.head && !value.tail && !value.mutex && !value.waiters);
    CHECK(sync_mutex_read(&mutex).owner==(uint32_t)(uintptr_t)&root);
    CHECK(admissions==1 && settlements==1 && timers==1 && stops==1 && parks==1 && wakes==1);
    CHECK(pthread_mutex_unlock(&mutex)==0);return 0;
}
__attribute__((export_name("terminal_cancel"))) int terminal_cancel(void) {
    reset();active=&child;require(pthread_mutex_lock(&mutex)==0);active=&root;
    next_error=3;const struct timespec future={2000000001,500000000};
    return pthread_mutex_timedlock(&mutex,&future);
}
__attribute__((export_name("terminal_deadline"))) int terminal_deadline(void) {
    reset();active=&child;require(pthread_mutex_lock(&mutex)==0);active=&root;
    next_error=4;const struct timespec future={2000000001,500000000};
    return pthread_mutex_timedlock(&mutex,&future);
}
__attribute__((export_name("terminal_cancel_after_notification"))) int terminal_cancel_after_notification(void) {
    reset();active=&child;require(pthread_mutex_lock(&mutex)==0);active=&root;
    next_error=3;on_timer_next=child_unlock_and_cancel;
    const struct timespec future={2000000001,500000000};
    return pthread_mutex_timedlock(&mutex,&future);
}
__attribute__((export_name("refusal_cancel_before_wake"))) int refusal_cancel_before_wake(void) {
    reset();active=&child;require(pthread_mutex_lock(&mutex)==0);active=&root;
    next_error=2;on_timer_next=cancel_before_wake;
    const struct timespec future={2000000001,500000000};
    return pthread_mutex_timedlock(&mutex,&future);
}
__attribute__((export_name("refusal_notification_cancel_before_wake"))) int refusal_notification_cancel_before_wake(void) {
    reset();active=&child;require(pthread_mutex_lock(&mutex)==0);active=&root;
    next_error=2;on_timer_next=child_unlock_and_cancel;
    const struct timespec future={2000000001,500000000};
    return pthread_mutex_timedlock(&mutex,&future);
}
__attribute__((export_name("terminal_state"))) int terminal_state(void) {
    CHECK(admissions==1 && settlements==0 && timers==1 && parks==1 && next_calls==1 && !wakes);
    if (global_cancel) {
        CHECK((next_error==2 || next_error==3) && wake_attempts==1);
        struct sync_mutex value=sync_mutex_read(&mutex);
        if (stops==1) CHECK(value.owner==(uint32_t)(uintptr_t)&root && !value.head && !value.waiters);
        else CHECK(!stops && value.owner==(uint32_t)(uintptr_t)&child && value.head && value.waiters==1);
    } else CHECK((next_error==3 || next_error==4) && !stops && !wake_attempts);
    return 0;
}


/* Explicit broker/timer doubles; not an engine, real ledger, or signed run. */
static __wasi_subscription_t poll_request;
static __wasi_event_t poll_event;
static __wasi_size_t poll_count;
static void poll_reset(uint64_t nanos) {
    reset();
    memset(&poll_request,0,sizeof(poll_request));
    memset(&poll_event,0,sizeof(poll_event));
    poll_request.userdata=UINT64_C(0x1122334455667788);
    poll_request.u.tag=__WASI_EVENTTYPE_CLOCK;
    poll_request.u.u.clock.id=__WASI_CLOCKID_REALTIME;
    poll_request.u.u.clock.timeout=nanos;
    poll_event.userdata=UINT64_C(0x9988776655443322);
    poll_event.type=77;
    poll_count=99;
}
static int poll_call(int count) {
    return __imported_wasi_snapshot_preview1_poll_oneoff((int32_t)(uintptr_t)&poll_request,
             (int32_t)(uintptr_t)&poll_event,count,(int32_t)(uintptr_t)&poll_count);
}
static int poll_unchanged(void) {
    return poll_event.userdata==UINT64_C(0x9988776655443322) && poll_event.type==77 && poll_count==99;
}
static void poll_during_next(void) {
    require(poll_unchanged() && admissions==1 && settlements==0 && timers==1 &&
            stops==0 && parks==1 && wakes==0 && admitted_nanos==5000000);
    /* Mutation during the host wait must not alter the selected input. */
    poll_request.userdata=0;
    poll_request.u.u.clock.timeout=0;
}
__attribute__((export_name("poll_clock_zero"))) int poll_clock_zero(void) {
    poll_reset(0);
    CHECK(poll_call(1)==0 && poll_count==1 && poll_event.type==__WASI_EVENTTYPE_CLOCK);
    CHECK(poll_event.userdata==UINT64_C(0x1122334455667788) && !poll_event.error);
    CHECK(!admissions && !timers && !parks && !stops && !settlements && source_errno==37);
    return 0;
}
__attribute__((export_name("poll_clock_elapsed"))) int poll_clock_elapsed(void) {
    poll_reset(5000000);on_timer_next=poll_during_next;
    CHECK(poll_call(1)==0 && poll_count==1 && poll_event.type==__WASI_EVENTTYPE_CLOCK);
    CHECK(poll_event.userdata==UINT64_C(0x1122334455667788) && !poll_event.error);
    CHECK(admissions==1 && settlements==1 && timers==1 && stops==1 && parks==1 && wakes==1);
    CHECK(next_calls==1 && admitted_nanos==5000000 && source_errno==37);return 0;
}
__attribute__((export_name("poll_clock_refusals"))) int poll_clock_refusals(void) {
    poll_reset(5000000);refuse_wait=1;
    CHECK(poll_call(1)==__WASI_ERRNO_AGAIN && poll_unchanged());
    CHECK(admissions==1 && !settlements && !timers && !parks);
    poll_reset(5000000);refuse_timer=1;
    CHECK(poll_call(1)==__WASI_ERRNO_AGAIN && poll_unchanged());
    CHECK(admissions==1 && settlements==1 && timers==1 && !stops && !parks);
    poll_reset(5000000);next_error=2;
    CHECK(poll_call(1)==__WASI_ERRNO_AGAIN && poll_unchanged());
    CHECK(admissions==1 && settlements==1 && timers==1 && stops==1 && parks==1 && wakes==1);
    return 0;
}
__attribute__((export_name("poll_clock_invalid"))) int poll_clock_invalid(void) {
    poll_reset(5000000);
    CHECK(poll_call(0)==__WASI_ERRNO_INVAL);
    CHECK(poll_call(2)==__WASI_ERRNO_NOTSUP);
    poll_request.u.tag=__WASI_EVENTTYPE_FD_READ;CHECK(poll_call(1)==__WASI_ERRNO_NOTSUP);
    poll_request.u.tag=__WASI_EVENTTYPE_FD_WRITE;CHECK(poll_call(1)==__WASI_ERRNO_NOTSUP);
    poll_request.u.tag=__WASI_EVENTTYPE_CLOCK;
    poll_request.u.u.clock.id=__WASI_CLOCKID_MONOTONIC;CHECK(poll_call(1)==__WASI_ERRNO_NOTSUP);
    poll_request.u.u.clock.id=__WASI_CLOCKID_REALTIME;poll_request.u.u.clock.flags=1;
    CHECK(poll_call(1)==__WASI_ERRNO_NOTSUP);poll_request.u.u.clock.flags=0;
    CHECK(__imported_wasi_snapshot_preview1_poll_oneoff(-1,(int32_t)(uintptr_t)&poll_event,1,
          (int32_t)(uintptr_t)&poll_count)==__WASI_ERRNO_FAULT);
    CHECK(__imported_wasi_snapshot_preview1_poll_oneoff((int32_t)(uintptr_t)&poll_request,-1,1,
          (int32_t)(uintptr_t)&poll_count)==__WASI_ERRNO_FAULT);
    CHECK(__imported_wasi_snapshot_preview1_poll_oneoff((int32_t)(uintptr_t)&poll_request,
          (int32_t)(uintptr_t)&poll_event,1,-1)==__WASI_ERRNO_FAULT);
    CHECK(__imported_wasi_snapshot_preview1_poll_oneoff((int32_t)(uintptr_t)&poll_request,
          (int32_t)(uintptr_t)&poll_event,1,(int32_t)(uintptr_t)&poll_event)==__WASI_ERRNO_INVAL);
    CHECK(poll_unchanged() && !admissions && !timers && source_errno==37);
    return 0;
}
__attribute__((export_name("poll_terminal_cancel"))) int poll_terminal_cancel(void) {
    poll_reset(5000000);next_error=3;return poll_call(1);
}
__attribute__((export_name("poll_terminal_deadline"))) int poll_terminal_deadline(void) {
    poll_reset(5000000);next_error=4;return poll_call(1);
}
__attribute__((export_name("poll_terminal_state"))) int poll_terminal_state(void) {
    CHECK(poll_unchanged() && admissions==1 && !settlements && timers==1 && !stops);
    CHECK(parks==1 && !wakes && next_calls==1);return 0;
}


static union {
    __wasi_subscription_t input;
    __wasi_event_t output;
} poll_alias;
static void poll_event_alias_pending(void) {
    require(poll_count==99 && admissions==1 && !settlements && timers==1 && !stops);
    require(poll_alias.input.userdata==UINT64_C(0x1122334455667788));
    poll_alias.input.userdata=0;
}
static void poll_count_alias_pending(void) {
    require(poll_unchanged() && admissions==1 && !settlements && timers==1 && !stops);
    require(poll_request.userdata==UINT64_C(0x1122334455667788));
    poll_request.userdata=0;
}
__attribute__((export_name("poll_clock_max"))) int poll_clock_max(void) {
    poll_reset(UINT64_MAX);
    CHECK(poll_call(1)==0 && poll_count==1 && poll_event.type==__WASI_EVENTTYPE_CLOCK);
    CHECK(poll_event.userdata==UINT64_C(0x1122334455667788) && !poll_event.error);
    CHECK(admitted_nanos==UINT64_MAX && admissions==1 && settlements==1 &&
          timers==1 && stops==1 && parks==1 && wakes==1);
    return 0;
}
__attribute__((export_name("poll_clock_aliases"))) int poll_clock_aliases(void) {
    poll_reset(5000000);poll_alias.input=poll_request;on_timer_next=poll_event_alias_pending;
    CHECK(__imported_wasi_snapshot_preview1_poll_oneoff((int32_t)(uintptr_t)&poll_alias.input,
          (int32_t)(uintptr_t)&poll_alias.output,1,(int32_t)(uintptr_t)&poll_count)==0);
    CHECK(poll_count==1 && poll_alias.output.userdata==UINT64_C(0x1122334455667788) &&
          poll_alias.output.type==__WASI_EVENTTYPE_CLOCK && !poll_alias.output.error);
    CHECK(admissions==1 && settlements==1 && timers==1 && stops==1 && admitted_nanos==5000000);
    poll_reset(5000000);on_timer_next=poll_count_alias_pending;
    CHECK(__imported_wasi_snapshot_preview1_poll_oneoff((int32_t)(uintptr_t)&poll_request,
          (int32_t)(uintptr_t)&poll_event,1,(int32_t)(uintptr_t)&poll_request)==0);
    __wasi_size_t count;memcpy(&count,&poll_request,sizeof(count));
    CHECK(count==1 && poll_event.userdata==UINT64_C(0x1122334455667788) &&
          poll_event.type==__WASI_EVENTTYPE_CLOCK && !poll_event.error);
    CHECK(admissions==1 && settlements==1 && timers==1 && stops==1 && admitted_nanos==5000000);
    return 0;
}

#if defined(LSF_C_TEST_LIBC_SELECT)
#include <sys/select.h>
static void poll_libc_during_next(void) {
    require(admissions==1 && !settlements && timers==1 && !stops &&
            parks==1 && !wakes && admitted_nanos==5000000);
}
__attribute__((export_name("poll_clock_via_libc"))) int poll_clock_via_libc(void) {
    poll_reset(5000000);on_timer_next=poll_libc_during_next;
    struct timeval timeout={.tv_sec=0,.tv_usec=5000};
    CHECK(select(0,NULL,NULL,NULL,&timeout)==0);
    CHECK(admissions==1 && settlements==1 && timers==1 && stops==1 && parks==1 && wakes==1);
    CHECK(next_calls==1 && admitted_nanos==5000000);return 0;
}
#endif
