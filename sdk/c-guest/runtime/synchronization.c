/* Private continuation of threads.c, selected only by its maintained profile.
 * Objects retain the pinned musl public layout. Wait nodes live on the actual
 * admitted C stack, and an original broker Wait precedes queue publication.
 * No allocator, broker call or user callback occurs while changing a queue.
 * Timed calls additionally require the compiler-selected standard clock PAL.
 * Robust and process-shared synchronization remain unsupported.
 */
#include <limits.h>

__attribute__((import_module("$root"),import_name("[thread-suspend]")))
uint32_t __lsf_c_sync_suspend(void);
__attribute__((import_module("$root"),import_name("[thread-resume-later]")))
void __lsf_c_sync_resume_later(uint32_t);

struct sync_wait {
    struct lsf_c_thread *thread;
    struct lsf_c_token owner;
    struct sync_wait *next;
    unsigned linked, notified, suspended;
#if LSF_C_TIMED_CLOCK
    struct lsf_c_token timer;
    uint64_t condition_sequence;
#endif
};
#if LSF_C_TIMED_CLOCK
#include <time.h>
_Static_assert(sizeof(time_t)==8 && sizeof(clockid_t)==4 && sizeof(struct timespec)==16,
               "pinned clock and timespec ABI");
static void sync_timer_retire(struct sync_wait *node);
static int sync_mutex_timed(void *,const struct timespec *);
static int sync_cond_timed(void *,void *,const struct timespec *);
#endif
/* Access opaque C11 and pthread objects through memcpy, not incompatible
 * structure lvalues. Both public types have the authenticated memory32 layout.
 */
struct sync_mutex {
    uint32_t type, owner, waiters;
    struct sync_wait *head, *tail;
    uint32_t count;
};
struct sync_cond {
    struct sync_wait *head, *tail;
    void *mutex;
    uint32_t waiters, clock;
    uint32_t reserved[7];
};
_Static_assert(sizeof(struct sync_mutex)==sizeof(pthread_mutex_t),"pinned pthread mutex layout");
_Static_assert(sizeof(struct sync_mutex)==sizeof(mtx_t),"pinned C11 mutex layout");
_Static_assert(sizeof(struct sync_cond)==sizeof(pthread_cond_t),"pinned pthread condition layout");
_Static_assert(sizeof(struct sync_cond)==sizeof(cnd_t),"pinned C11 condition layout");
_Static_assert(sizeof(pthread_mutexattr_t)==sizeof(uint32_t),"pinned mutex attribute layout");
_Static_assert(sizeof(pthread_condattr_t)==sizeof(uint32_t),"pinned condition attribute layout");

static struct sync_mutex sync_mutex_read(const void *object) {
    struct sync_mutex value;memcpy(&value,object,sizeof(value));return value;
}
static void sync_mutex_write(void *object,struct sync_mutex value) {
    memcpy(object,&value,sizeof(value));
}
static struct sync_cond sync_cond_read(const void *object) {
    struct sync_cond value;memcpy(&value,object,sizeof(value));return value;
}
static void sync_cond_write(void *object,struct sync_cond value) {
    memcpy(object,&value,sizeof(value));
}
#if LSF_C_TIMED_CLOCK
static uint64_t sync_cond_sequence(struct sync_cond value) {
    return (uint64_t)value.reserved[0]|((uint64_t)value.reserved[1]<<32);
}
static int sync_cond_publish_sequence(struct sync_cond *value,struct sync_wait *node) {
    uint64_t sequence=sync_cond_sequence(*value);
    if (sequence==UINT64_MAX) return EAGAIN;
    ++sequence;value->reserved[0]=(uint32_t)sequence;value->reserved[1]=(uint32_t)(sequence>>32);
    node->condition_sequence=sequence;return 0;
}
#endif
static uint32_t sync_identity(void) { return (uint32_t)(uintptr_t)current(); }
static int sync_begin(struct sync_wait *node) {
    struct lsf_c_thread *caller=current();
    int error=ensure_root_owners(caller->root);
    if (error) return error;
    *node=(struct sync_wait){.thread=caller};
    error=acquire(LSF_C_WAIT,&caller->task,&node->owner);
    if (!error) require(current()==caller);
    return error;
}
static void sync_end(struct sync_wait *node) {
    require(!node->linked && !node->suspended && current()==node->thread);
#if LSF_C_TIMED_CLOCK
    sync_timer_retire(node);
#endif
    settle(&node->owner);
}
static void sync_await(struct sync_wait *node) {
    require(current()==node->thread);
    if (node->notified) return;
    /* The broker operation may await host execution. A notifier can run
     * during that call, so recheck AFTER it before canonical suspension.
     * Between publishing suspended and the intrinsic there is no host call.
     */
    park(node->thread->task);
    if (!node->notified) {
        node->suspended=1;
        uint32_t cancelled=__lsf_c_sync_suspend();
        node->suspended=0;
        /* Cancellation is terminal activation interruption, never a
         * successful lock/signal. A trap retains the original owners.
         */
        require(cancelled==0 && node->notified && current()==node->thread);
    }
    wake(node->thread->task);
}
static void sync_notify(struct sync_wait *node) {
    require(!node->linked && !node->notified);
    node->notified=1;
#if LSF_C_TIMED_CLOCK
    if (token_live(node->timer)) {
        require(!node->suspended);
        /* The timer is claimed before the call. Its waiter can return and
         * destroy this node while timer-stop is awaiting; never read it again. */
        sync_timer_retire(node);
        return;
    }
#endif
    if (node->suspended) {
        uint32_t target=node->thread->canonical_id;
        /* All state and links are final BEFORE exposing the continuation.
         * No node access follows the actual canonical wake operation.
         */
        __lsf_c_sync_resume_later(target);
    }
}
static int sync_mutex_valid(struct sync_mutex value) {
    return value.type<=PTHREAD_MUTEX_ERRORCHECK &&
        ((value.head==NULL)==(value.tail==NULL)) &&
        ((value.waiters==0)==(value.head==NULL)) &&
        ((value.owner==0)==(value.count==0));
}
static int sync_try(void *object,int blocking) {
    if (object==NULL) return EINVAL;
    struct sync_mutex value=sync_mutex_read(object);
    if (!sync_mutex_valid(value)) return EINVAL;
    uint32_t identity=sync_identity();
    if (!value.owner) {
        require(!value.waiters);value.owner=identity;value.count=1;
        sync_mutex_write(object,value);__atomic_signal_fence(__ATOMIC_ACQUIRE);return 0;
    }
    if (value.owner==identity) {
        if (value.type==PTHREAD_MUTEX_RECURSIVE) {
            if (value.count>=INT_MAX) return EAGAIN;
            ++value.count;sync_mutex_write(object,value);__atomic_signal_fence(__ATOMIC_ACQUIRE);return 0;
        }
        if (blocking && value.type==PTHREAD_MUTEX_ERRORCHECK) return EDEADLK;
    }
    return EBUSY;
}
static int sync_lock_with_wait(void *object,struct sync_wait *node) {
    int error=sync_try(object,1);
    if (error!=EBUSY) return error;
    struct sync_mutex value=sync_mutex_read(object);
    if (value.waiters==UINT32_MAX) return EAGAIN;
    node->next=NULL;node->linked=1;node->notified=0;
    if (value.tail) value.tail->next=node;else value.head=node;
    value.tail=node;++value.waiters;sync_mutex_write(object,value);
    sync_await(node);
    value=sync_mutex_read(object);
    require(!node->linked && value.owner==sync_identity() && value.count==1);
    __atomic_signal_fence(__ATOMIC_ACQUIRE);
    return 0;
}
static int sync_lock(void *object) {
    int error=sync_try(object,1);
    if (error!=EBUSY) return error;
    struct sync_wait node;
    error=sync_begin(&node);
    if (error) return error;
    /* Admission may await, so retry the actual mutex after it returns. */
    error=sync_lock_with_wait(object,&node);sync_end(&node);return error;
}
static int sync_unlock(void *object) {
    if (object==NULL) return EINVAL;
    struct sync_mutex value=sync_mutex_read(object);
    if (!sync_mutex_valid(value)) return EINVAL;
    if (value.owner!=sync_identity()) return EPERM;
    __atomic_signal_fence(__ATOMIC_RELEASE);
    if (value.count>1) { --value.count;sync_mutex_write(object,value);return 0; }
    struct sync_wait *next=value.head;
    if (next) {
        value.head=next->next;if (!value.head) value.tail=NULL;
        require(value.waiters!=0);--value.waiters;
        value.owner=(uint32_t)(uintptr_t)next->thread;value.count=1;
        next->next=NULL;next->linked=0;
    } else { value.owner=0;value.count=0; }
    sync_mutex_write(object,value);
    if (next) sync_notify(next);
    return 0;
}
static int sync_mutex_init(void *object,uint32_t type) {
    if (object==NULL || type>PTHREAD_MUTEX_ERRORCHECK) return EINVAL;
    sync_mutex_write(object,(struct sync_mutex){.type=type});return 0;
}
static int sync_mutex_destroy(void *object) {
    if (object==NULL) return EINVAL;
    struct sync_mutex value=sync_mutex_read(object);
    if (!sync_mutex_valid(value)) return EINVAL;
    if (value.owner || value.waiters) return EBUSY;
    sync_mutex_write(object,(struct sync_mutex){0});return 0;
}
int pthread_mutex_init(pthread_mutex_t *restrict object,const pthread_mutexattr_t *restrict attr) {
    int saved=errno;uint32_t type=0;if (attr) memcpy(&type,attr,sizeof(type));
    int error=type>PTHREAD_MUTEX_ERRORCHECK?ENOTSUP:sync_mutex_init(object,type);
    errno=saved;return error;
}
int __pthread_mutex_lock(pthread_mutex_t *object) { int saved=errno,error=sync_lock(object);errno=saved;return error; }
int pthread_mutex_lock(pthread_mutex_t *object) { return __pthread_mutex_lock(object); }
int __pthread_mutex_trylock(pthread_mutex_t *object) { int saved=errno,error=sync_try(object,0);errno=saved;return error; }
int pthread_mutex_trylock(pthread_mutex_t *object) { return __pthread_mutex_trylock(object); }
int __pthread_mutex_unlock(pthread_mutex_t *object) { int saved=errno,error=sync_unlock(object);errno=saved;return error; }
int pthread_mutex_unlock(pthread_mutex_t *object) { return __pthread_mutex_unlock(object); }
int pthread_mutex_destroy(pthread_mutex_t *object) { int saved=errno,error=sync_mutex_destroy(object);errno=saved;return error; }
int pthread_mutex_timedlock(pthread_mutex_t *restrict object,const struct timespec *restrict deadline) {
#if LSF_C_TIMED_CLOCK
    int saved=errno,error=sync_mutex_timed(object,deadline);errno=saved;return error;
#else
    (void)object;(void)deadline;return ENOTSUP;
#endif
}
int mtx_init(mtx_t *object,int type) {
#if LSF_C_TIMED_CLOCK
    int saved=errno;int error=type<0 || type>(mtx_recursive|mtx_timed)?ENOTSUP:
        sync_mutex_init(object,(type&mtx_recursive)?PTHREAD_MUTEX_RECURSIVE:PTHREAD_MUTEX_NORMAL);
#else
    int saved=errno;int error=(type!=mtx_plain && type!=mtx_recursive)?ENOTSUP:
        sync_mutex_init(object,type==mtx_recursive?PTHREAD_MUTEX_RECURSIVE:PTHREAD_MUTEX_NORMAL);
#endif
    errno=saved;return error?thrd_error:thrd_success;
}
int mtx_lock(mtx_t *object) { int saved=errno,error=sync_lock(object);errno=saved;return error?thrd_error:thrd_success; }
int mtx_trylock(mtx_t *object) { int saved=errno,error=sync_try(object,0);errno=saved;return !error?thrd_success:error==EBUSY?thrd_busy:thrd_error; }
int mtx_unlock(mtx_t *object) { int saved=errno,error=sync_unlock(object);errno=saved;return error?thrd_error:thrd_success; }
void mtx_destroy(mtx_t *object) { int saved=errno;(void)sync_mutex_destroy(object);errno=saved; }
int mtx_timedlock(mtx_t *restrict object,const struct timespec *restrict deadline) {
#if LSF_C_TIMED_CLOCK
    int saved=errno,error=sync_mutex_timed(object,deadline);errno=saved;
    return error==0?thrd_success:error==ETIMEDOUT?thrd_timedout:error==ENOMEM?thrd_nomem:thrd_error;
#else
    (void)object;(void)deadline;return thrd_error;
#endif
}

static int sync_cond_valid(struct sync_cond value) {
    return value.clock<=1 && ((value.head==NULL)==(value.tail==NULL)) &&
        ((value.waiters==0)==(value.head==NULL)) && ((value.mutex==NULL)==(value.head==NULL));
}
static int sync_cond_init(void *object,uint32_t clock) {
    if (object==NULL || clock>1) return EINVAL;
    sync_cond_write(object,(struct sync_cond){.clock=clock});return 0;
}
static int sync_cond_destroy(void *object) {
    if (object==NULL) return EINVAL;
    struct sync_cond value=sync_cond_read(object);
    if (!sync_cond_valid(value)) return EINVAL;
    if (value.waiters) return EBUSY;
    sync_cond_write(object,(struct sync_cond){0});return 0;
}
static int sync_cond_wait(void *object,void *mutex) {
    if (object==NULL || mutex==NULL) return EINVAL;
    struct sync_cond value=sync_cond_read(object);
    struct sync_mutex locked=sync_mutex_read(mutex);
    if (!sync_cond_valid(value) || !sync_mutex_valid(locked)) return EINVAL;
    if (locked.owner!=sync_identity()) return EPERM;
    /* The selected profile requires one held recursive level at wait entry. */
    if (locked.count!=1 || (value.mutex && value.mutex!=mutex)) return EINVAL;
    struct sync_wait node;int error=sync_begin(&node);
    if (error) return error; /* Mutex remains held on admission refusal. */
    value=sync_cond_read(object);locked=sync_mutex_read(mutex);
    if (!sync_cond_valid(value) || !sync_mutex_valid(locked) || locked.owner!=sync_identity() ||
            locked.count!=1 || (value.mutex && value.mutex!=mutex) || value.waiters==UINT32_MAX) {
        sync_end(&node);return EINVAL;
    }
#if LSF_C_TIMED_CLOCK
    error=sync_cond_publish_sequence(&value,&node);
    if (error) { sync_end(&node);return error; }
#endif
    node.linked=1;node.next=NULL;
    if (value.tail) value.tail->next=&node;else value.head=&node;
    value.tail=&node;value.mutex=mutex;++value.waiters;sync_cond_write(object,value);
    /* Publish the waiter BEFORE releasing the associated mutex. */
    require(sync_unlock(mutex)==0);sync_await(&node);
    require(!node.linked);
    /* Keep the SAME admitted Wait through mutex reacquisition. A fresh Wait
     * refusal must not return from cond_wait with the mutex still unlocked.
     */
    error=sync_lock_with_wait(mutex,&node);require(error==0);
    sync_end(&node);return 0;
}
static int sync_cond_wake(void *object,int all) {
    if (object==NULL) return EINVAL;
    struct sync_cond value=sync_cond_read(object);
    if (!sync_cond_valid(value)) return EINVAL;
#if LSF_C_TIMED_CLOCK
    /* timer-stop may await. Never detach a list of stack nodes or retain its
     * next pointer across notification: a different timer may expire and
     * destroy that stack. Each removal linearizes against the live queue.
     * The closed sequence wave excludes waiters published during the call. */
    uint64_t cutoff=sync_cond_sequence(value);unsigned visited=0;
    for (;;) {
        struct sync_wait *first=value.head;
        if (!first || first->condition_sequence>cutoff) break;
        require(++visited<=RECORD_LIMIT+1u && first->condition_sequence!=0);
        value.head=first->next;require(value.waiters!=0);--value.waiters;
        if (!value.head) { value.tail=NULL;value.mutex=NULL; }
        sync_cond_write(object,value);first->next=NULL;first->linked=0;
        sync_notify(first); /* No access to first or cached next after await. */
        if (!all) break;
        value=sync_cond_read(object);require(sync_cond_valid(value));
    }
#else
    struct sync_wait *first=value.head;
    if (first) {
        if (all) { value.head=value.tail=NULL;value.waiters=0; }
        else { value.head=first->next;require(value.waiters!=0);--value.waiters;
            if (!value.head) value.tail=NULL; }
        if (!value.head) value.mutex=NULL;
        sync_cond_write(object,value);
        do {
            struct sync_wait *next=all?first->next:NULL;
            first->next=NULL;first->linked=0;sync_notify(first);first=next;
        } while (first);
    }
#endif
    return 0;
}
int pthread_cond_init(pthread_cond_t *restrict object,const pthread_condattr_t *restrict attr) {
    int saved=errno;uint32_t clock=0;if (attr) memcpy(&clock,attr,sizeof(clock));
    int error=clock>1?ENOTSUP:sync_cond_init(object,clock);errno=saved;return error;
}
int pthread_cond_destroy(pthread_cond_t *object) { int saved=errno,error=sync_cond_destroy(object);errno=saved;return error; }
int pthread_cond_wait(pthread_cond_t *restrict object,pthread_mutex_t *restrict mutex) {
    int saved=errno,error=sync_cond_wait(object,mutex);errno=saved;return error;
}
int pthread_cond_signal(pthread_cond_t *object) { int saved=errno,error=sync_cond_wake(object,0);errno=saved;return error; }
int pthread_cond_broadcast(pthread_cond_t *object) { int saved=errno,error=sync_cond_wake(object,1);errno=saved;return error; }
int pthread_cond_timedwait(pthread_cond_t *restrict object,pthread_mutex_t *restrict mutex,const struct timespec *restrict deadline) {
#if LSF_C_TIMED_CLOCK
    int saved=errno,error=sync_cond_timed(object,mutex,deadline);errno=saved;return error;
#else
    (void)object;(void)mutex;(void)deadline;return ENOTSUP;
#endif
}
int cnd_init(cnd_t *object) { int saved=errno,error=sync_cond_init(object,0);errno=saved;return error?thrd_error:thrd_success; }
void cnd_destroy(cnd_t *object) { int saved=errno;(void)sync_cond_destroy(object);errno=saved; }
int cnd_wait(cnd_t *object,mtx_t *mutex) { int saved=errno,error=sync_cond_wait(object,mutex);errno=saved;return error?thrd_error:thrd_success; }
int cnd_signal(cnd_t *object) { int saved=errno,error=sync_cond_wake(object,0);errno=saved;return error?thrd_error:thrd_success; }
int cnd_broadcast(cnd_t *object) { int saved=errno,error=sync_cond_wake(object,1);errno=saved;return error?thrd_error:thrd_success; }
int cnd_timedwait(cnd_t *restrict object,mtx_t *restrict mutex,const struct timespec *restrict deadline) {
#if LSF_C_TIMED_CLOCK
    int saved=errno,error=sync_cond_timed(object,mutex,deadline);errno=saved;
    return error==0?thrd_success:error==ETIMEDOUT?thrd_timedout:thrd_error;
#else
    (void)object;(void)mutex;(void)deadline;return thrd_error;
#endif
}

#if LSF_C_TIMED_CLOCK
/* Timed waits use the real timer-next host await, never manual promotion of a
 * canonical thread whose engine host future is still live. A signal closes
 * that exact Timer, and the waiter rechecks authoritative Task liveness. */
struct sync_timer_result {
    uint8_t tag,pad[7];
    union { uint64_t skipped; uint8_t error; } value;
};
_Static_assert(sizeof(struct sync_timer_result)==16,"canonical timer-next result");
__attribute__((import_module("latent:runtime/activation@0.1.0"),import_name("timer-start")))
void sync_host_timer_start(uint64_t,uint32_t,uint64_t,uint32_t,uint64_t,uint64_t,struct token_result *);
__attribute__((import_module("latent:runtime/activation@0.1.0"),import_name("timer-next")))
void sync_host_timer_next(uint64_t,uint64_t,struct sync_timer_result *);
__attribute__((import_module("latent:runtime/activation@0.1.0"),import_name("timer-stop")))
void sync_host_timer_stop(uint64_t,uint64_t,struct unit_result *);

static void sync_timer_retire(struct sync_wait *node) {
    struct lsf_c_token timer=node->timer;
    if (!token_live(timer)) return;
    node->timer=(struct lsf_c_token){0};
    struct unit_result result={255,255};
    sync_host_timer_stop(timer.generation,timer.id,&result);
    require(result.tag==0); /* No access to node after the awaiting host call. */
}
static int sync_timer_start(struct sync_wait *node,uint64_t nanos) {
    require(!node->linked && !node->suspended && !token_live(node->timer));
    struct token_result result={0};
    sync_host_timer_start(nanos,0,0,1,node->owner.generation,node->owner.id,&result);
    require(current()==node->thread);
    if (result.tag==1) return runtime_error(result.value.error);
    require(result.tag==0 && token_live(result.value.token));
    node->timer=result.value.token;return 0;
}
static int sync_duration(const struct timespec *value,uint64_t *nanos) {
    if (!value || value->tv_sec<0 || value->tv_nsec<0 || value->tv_nsec>=1000000000) return EINVAL;
    uint64_t seconds=(uint64_t)value->tv_sec,fraction=(uint64_t)value->tv_nsec;
    if (seconds>(UINT64_MAX-fraction)/1000000000u) return EOVERFLOW;
    *nanos=seconds*1000000000u+fraction;return 0;
}
static int sync_remaining(uint32_t clock,const struct timespec *deadline,uint64_t *nanos) {
    uint64_t absolute,now;struct timespec sample;
    int error=sync_duration(deadline,&absolute);
    if (error) return error;
    /* The original WASI libc clockid_t is an authenticated pointer, while its
     * pthread condition attribute stores the clock's numeric WASI id. */
    if (clock>1) return ENOTSUP;
    if (clock_gettime(clock==0?CLOCK_REALTIME:CLOCK_MONOTONIC,&sample)!=0) return errno;
    error=sync_duration(&sample,&now);if (error) return error;
    *nanos=absolute>now?absolute-now:0;return 0;
}
static int sync_await_timer(struct sync_wait *node) {
    require(current()==node->thread && !node->suspended);
    if (node->notified) return 0;
    struct lsf_c_token timer=node->timer;require(token_live(timer));
    park(node->thread->task);
    if (!node->notified) {
        struct sync_timer_result result={.tag=255};
        sync_host_timer_next(timer.generation,timer.id,&result);
        require(current()==node->thread);
        /* Local stop is accepted only after this exact queue notification.
         * Global cancellation/deadline never becomes requested elapsed time. */
        require((result.tag==0 && result.value.skipped==0) ||
            (result.tag==1 && result.value.error==3 && node->notified));
    }
    wake(node->thread->task);
    return node->notified?0:ETIMEDOUT;
}
static void sync_remove(struct sync_wait **head,struct sync_wait **tail,uint32_t *count,
                        struct sync_wait *node) {
    struct sync_wait *previous=NULL,*cursor=*head;unsigned visited=0;
    require(node->linked && *count!=0);
    while (cursor && cursor!=node) {
        require(++visited<=RECORD_LIMIT+1u);previous=cursor;cursor=cursor->next;
    }
    require(cursor==node);
    if (previous) previous->next=node->next;else *head=node->next;
    if (*tail==node) *tail=previous;
    --*count;node->linked=0;node->next=NULL;
}
static int sync_mutex_timed(void *object,const struct timespec *deadline) {
    int error=sync_try(object,1);if (error!=EBUSY) return error;
    uint64_t nanos;error=sync_remaining(0,deadline,&nanos);
    if (error || nanos==0) return error?error:ETIMEDOUT;
    struct sync_wait node;error=sync_begin(&node);if (error) return error;
    error=sync_try(object,1);if (error!=EBUSY) { sync_end(&node);return error; }
    error=sync_remaining(0,deadline,&nanos);
    if (!error && nanos!=0) error=sync_timer_start(&node,nanos);
    if (error || nanos==0) { sync_end(&node);return error?error:ETIMEDOUT; }
    /* Timer admission may await. Recheck the actual mutex before publication. */
    error=sync_try(object,1);if (error!=EBUSY) { sync_end(&node);return error; }
    struct sync_mutex value=sync_mutex_read(object);
    if (value.waiters==UINT32_MAX) { sync_end(&node);return EAGAIN; }
    node.linked=1;node.next=NULL;
    if (value.tail) value.tail->next=&node;else value.head=&node;
    value.tail=&node;++value.waiters;sync_mutex_write(object,value);
    error=sync_await_timer(&node);value=sync_mutex_read(object);
    if (error==ETIMEDOUT) {
        sync_remove(&value.head,&value.tail,&value.waiters,&node);
        sync_mutex_write(object,value);
    } else {
        require(!node.linked && value.owner==sync_identity() && value.count==1);
        __atomic_signal_fence(__ATOMIC_ACQUIRE);
    }
    sync_end(&node);return error;
}
static int sync_cond_timed(void *object,void *mutex,const struct timespec *deadline) {
    if (!object || !mutex) return EINVAL;
    struct sync_cond value=sync_cond_read(object);struct sync_mutex locked=sync_mutex_read(mutex);
    if (!sync_cond_valid(value) || !sync_mutex_valid(locked)) return EINVAL;
    if (locked.owner!=sync_identity()) return EPERM;
    if (locked.count!=1 || (value.mutex && value.mutex!=mutex)) return EINVAL;
    uint64_t nanos;int error=sync_remaining(value.clock,deadline,&nanos);
    if (error) return error;
    struct sync_wait node;error=sync_begin(&node);if (error) return error;
    value=sync_cond_read(object);locked=sync_mutex_read(mutex);
    if (!sync_cond_valid(value) || !sync_mutex_valid(locked) || locked.owner!=sync_identity() ||
            locked.count!=1 || (value.mutex && value.mutex!=mutex) || value.waiters==UINT32_MAX) {
        sync_end(&node);return EINVAL;
    }
    error=sync_remaining(value.clock,deadline,&nanos);
    if (!error && nanos!=0) error=sync_timer_start(&node,nanos);
    if (error) { sync_end(&node);return error; }
    /* Preserve the actual mutex through admission refusal and recheck after
     * every potentially awaiting admission, before touching the queue. */
    value=sync_cond_read(object);locked=sync_mutex_read(mutex);
    if (!sync_cond_valid(value) || !sync_mutex_valid(locked) || locked.owner!=sync_identity() ||
            locked.count!=1 || (value.mutex && value.mutex!=mutex) || value.waiters==UINT32_MAX) {
        sync_end(&node);return EINVAL;
    }
    if (nanos!=0) {
        error=sync_cond_publish_sequence(&value,&node);
        if (error) { sync_end(&node);return error; }
        node.linked=1;node.next=NULL;
        if (value.tail) value.tail->next=&node;else value.head=&node;
        value.tail=&node;value.mutex=mutex;++value.waiters;sync_cond_write(object,value);
    }
    require(sync_unlock(mutex)==0);
    error=nanos==0?ETIMEDOUT:sync_await_timer(&node);
    if (node.linked) {
        require(error==ETIMEDOUT);value=sync_cond_read(object);
        sync_remove(&value.head,&value.tail,&value.waiters,&node);
        if (!value.head) value.mutex=NULL;
        sync_cond_write(object,value);
    }
    /* Timer close precedes untimed reacquisition. Retain the SAME Wait so a
     * second admission refusal cannot return with the mutex still unlocked. */
    sync_timer_retire(&node);
    require(sync_lock_with_wait(mutex,&node)==0);
    sync_end(&node);return error;
}
static int sync_sleep(const struct timespec *duration,struct timespec *remaining) {
    uint64_t nanos;int error=sync_duration(duration,&nanos);if (error) return error;
    if (nanos!=0) {
        struct sync_wait node;error=sync_begin(&node);if (error) return error;
        error=sync_timer_start(&node,nanos);
        if (!error) { require(sync_await_timer(&node)==ETIMEDOUT); }
        sync_end(&node);if (error) return error;
    }
    if (remaining) *remaining=(struct timespec){0};
    return 0;
}
int nanosleep(const struct timespec *duration,struct timespec *remaining) {
    int saved=errno,error=sync_sleep(duration,remaining);
    errno=error?error:saved;return error?-1:0;
}
int thrd_sleep(const struct timespec *duration,struct timespec *remaining) {
    int saved=errno,error=sync_sleep(duration,remaining);errno=saved;return error?-2:0;
}
#endif
