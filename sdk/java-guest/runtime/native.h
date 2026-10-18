/* TeaVM @Import functions need C declarations in its generated translation unit. */
#ifndef LSF_JAVA_NATIVE_H
#define LSF_JAVA_NATIVE_H
#include <stdint.h>
void *lsf_java_alloc(int32_t length);
void lsf_java_free(void *pointer);
void *lsf_java_host(int32_t operation, void *bytes, int32_t length);
void *lsf_java_async_begin(int32_t operation, void *bytes, int32_t length);
int32_t lsf_java_async_state(void *call);
void *lsf_java_async_take(void *call, int32_t cancelled_root_wait);
void lsf_java_async_poll(void);
void lsf_java_async_wait(void);
int32_t lsf_java_async_cancel_root_wait(void *call);
#endif
