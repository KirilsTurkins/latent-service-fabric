/* Ordinary source compiled separately with the maintained timed profile. */
#include <stddef.h>
#include <sys/select.h>

int timed_select_from_dependency(long microseconds) {
    struct timeval delay={.tv_sec=0,.tv_usec=microseconds};
    int (*operation)(int,fd_set *,fd_set *,fd_set *,struct timeval *)=select;
    return operation(0,NULL,NULL,NULL,&delay);
}
int timed_pselect_from_dependency(long nanoseconds) {
    const struct timespec delay={.tv_sec=0,.tv_nsec=nanoseconds};
    int (*operation)(int,fd_set *,fd_set *,fd_set *,const struct timespec *,const sigset_t *)=pselect;
    return operation(0,NULL,NULL,NULL,&delay,NULL);
}
