/* Ordinary APIs compiled beneath the selected C PAL. A linked core is not a
 * canonical-child execution or signed-runtime qualification.
 */
#include <errno.h>
#include <pthread.h>
#include <stdint.h>
#include <threads.h>

static _Thread_local unsigned local=7;
static pthread_t root_pthread;
static thrd_t root_c11;
static void require(int predicate) { if (!predicate) __builtin_trap(); }

static void *pthread_worker(void *argument) {
    require(!pthread_equal(pthread_self(),root_pthread));
    require(local==7);local+=(unsigned)(uintptr_t)argument;
    errno=37;return (void *)(uintptr_t)(local+(unsigned)errno);
}
static int c11_worker(void *argument) {
    require(!thrd_equal(thrd_current(),root_c11));
    require(local==7);local+=(unsigned)(uintptr_t)argument;
    errno=41;return (int)local+errno;
}

__attribute__((export_name("run")))
unsigned run(unsigned mode) {
    require(local==7);errno=23;
    if (mode==0) {
        root_pthread=pthread_self();pthread_t child;void *result=NULL;
        require(pthread_create(&child,NULL,pthread_worker,(void *)(uintptr_t)5)==0);
        require(local==7 && errno==23 && !pthread_equal(root_pthread,child));
        require(pthread_join(child,&result)==0 && (uintptr_t)result==49);
    } else {
        require(mode==1);root_c11=thrd_current();thrd_t child;int result=0;
        require(thrd_create(&child,c11_worker,(void *)(uintptr_t)9)==thrd_success);
        require(local==7 && errno==23 && !thrd_equal(root_c11,child));
        require(thrd_join(child,&result)==thrd_success && result==57);
    }
    require(local==7 && errno==23);return 30;
}
