/* The selected source and the exact pinned WASI libc stub are linked together.
 * No canonical thread, guest or original activation ledger is executed here. */
#define _GNU_SOURCE 1
#include <errno.h>
#include <pthread.h>
#include <stdint.h>
#include <time.h>

int pthread_tryjoin_np(pthread_t,void **);
int pthread_timedjoin_np(pthread_t,void **,const struct timespec *);
#include "c-gnu-join-reference-body.h"

static int marker;
__attribute__((export_name("expected"))) int expected(void) { return ENOTSUP; }
__attribute__((export_name("try_join"))) int try_join(void) {
    void *result=&marker;
    int error=pthread_tryjoin_np((pthread_t)(void *)&marker,&result);
    return result==&marker?error:-1;
}
__attribute__((export_name("timed_join"))) int timed_join(void) {
    void *result=&marker;const struct timespec deadline={0,0};
    int error=pthread_timedjoin_np((pthread_t)(void *)&marker,&result,&deadline);
    return result==&marker?error:-1;
}
