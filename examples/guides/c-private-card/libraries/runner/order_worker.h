#ifndef ORDER_WORKER_H
#define ORDER_WORKER_H
int order_run_request(int (*request)(void *), void *argument, int *outcome);
#endif
