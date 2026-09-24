/* TeaVM @Import functions need C declarations in its generated translation unit. */
#ifndef LSF_JAVA_NATIVE_H
#define LSF_JAVA_NATIVE_H
#include <stdint.h>
void *lsf_java_alloc(int32_t length);
void lsf_java_free(void *pointer);
void *lsf_java_host(int32_t operation, void *bytes, int32_t length);
#endif
