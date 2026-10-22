/* Private continuation of threads.c, selected only by its maintained profile.
 * Objects retain the pinned musl public layout. Wait nodes live on the actual
 * admitted C stack, and an original broker Wait precedes queue publication.
 * No allocator, broker call or user callback occurs while changing a queue.
 * Timed, robust and process-shared synchronization are separate profile work.
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
};
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
    (void)object;(void)deadline;return ENOTSUP;
}
int mtx_init(mtx_t *object,int type) {
    int saved=errno;int error=(type!=mtx_plain && type!=mtx_recursive)?ENOTSUP:
        sync_mutex_init(object,type==mtx_recursive?PTHREAD_MUTEX_RECURSIVE:PTHREAD_MUTEX_NORMAL);
    errno=saved;return error?thrd_error:thrd_success;
}
int mtx_lock(mtx_t *object) { int saved=errno,error=sync_lock(object);errno=saved;return error?thrd_error:thrd_success; }
int mtx_trylock(mtx_t *object) { int saved=errno,error=sync_try(object,0);errno=saved;return !error?thrd_success:error==EBUSY?thrd_busy:thrd_error; }
int mtx_unlock(mtx_t *object) { int saved=errno,error=sync_unlock(object);errno=saved;return error?thrd_error:thrd_success; }
void mtx_destroy(mtx_t *object) { int saved=errno;(void)sync_mutex_destroy(object);errno=saved; }
int mtx_timedlock(mtx_t *restrict object,const struct timespec *restrict deadline) {
    (void)object;(void)deadline;return thrd_error;
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
    (void)object;(void)mutex;(void)deadline;return ENOTSUP;
}
int cnd_init(cnd_t *object) { int saved=errno,error=sync_cond_init(object,0);errno=saved;return error?thrd_error:thrd_success; }
void cnd_destroy(cnd_t *object) { int saved=errno;(void)sync_cond_destroy(object);errno=saved; }
int cnd_wait(cnd_t *object,mtx_t *mutex) { int saved=errno,error=sync_cond_wait(object,mutex);errno=saved;return error?thrd_error:thrd_success; }
int cnd_signal(cnd_t *object) { int saved=errno,error=sync_cond_wake(object,0);errno=saved;return error?thrd_error:thrd_success; }
int cnd_broadcast(cnd_t *object) { int saved=errno,error=sync_cond_wake(object,1);errno=saved;return error?thrd_error:thrd_success; }
int cnd_timedwait(cnd_t *restrict object,mtx_t *restrict mutex,const struct timespec *restrict deadline) {
    (void)object;(void)mutex;(void)deadline;return thrd_error;
}
