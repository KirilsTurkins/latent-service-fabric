/* Only the isolated source control redirects errno. This does not test or
 * replace the selected libc's thread-local errno implementation. */
#include <errno.h>
extern int lsf_test_errno;
#undef errno
#define errno lsf_test_errno
