#include "order_worker.h"
#include <errno.h>
#include <pthread.h>
#include <stdlib.h>
struct request_job {
    int (*run)(void *);
    void *argument;
    pthread_t caller;
    int result;
    int saved_errno;
};
static void *complete_request(void *context) {
    struct request_job *job = context;
    if (pthread_equal(job->caller, pthread_self())) abort();
    errno = job->saved_errno;
    job->result = job->run(job->argument);
    job->saved_errno = errno;
    return context;
}
int order_run_request(int (*request)(void *), void *argument, int *outcome) {
    struct request_job job = {request, argument, pthread_self(), 0, errno};
    pthread_t worker;
    int error = pthread_create(&worker, NULL, complete_request, &job);
    if (error) return error;
    void *returned = NULL;
    if (pthread_join(worker, &returned) != 0 || returned != &job) abort();
    *outcome = job.result;
    errno = job.saved_errno;
    return 0;
}
