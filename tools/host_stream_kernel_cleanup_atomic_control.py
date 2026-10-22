"""Finite hosted native control for the exact maintained nonfinal CAS leaf.

This executes native compiler atomics with deterministic external-put/get
interleavings. It does not execute Linux, device destructors or native budgets.
"""
from tools import host_stream_kernel_cleanup_provider_nonfinal as source


def program():
    leaf = source.atomic_nonfinal()
    return ('''/* Generated control: only the atomic leaf is maintained Linux C.
 * Atomic shims and deterministic interference below are test infrastructure. */
#define EOPNOTSUPP 95
#define EOVERFLOW 75
#define EIO 5
#define REFCOUNT_SATURATED 0xc0000000u
#define unlikely(value) (value)
typedef struct { unsigned int refs; } refcount_t;
_Static_assert(sizeof(unsigned int) == 4, "Linux x86 unsigned width");
static int inject_delta, destructor_calls, attempts;
static unsigned int atomic_read(unsigned int *refs)
{
    return __atomic_load_n(refs, __ATOMIC_RELAXED);
}
static void external_put(unsigned int *refs)
{
    if (__atomic_fetch_sub(refs, 1u, __ATOMIC_RELEASE) == 1u) {
        __atomic_thread_fence(__ATOMIC_ACQUIRE);
        destructor_calls++; /* Observation only; no device destructor. */
    }
}
static int atomic_try_cmpxchg_release(unsigned int *refs,
    unsigned int *expected, unsigned int desired)
{
    attempts++;
    if (inject_delta < 0) {
        inject_delta = 0;
        external_put(refs);
    } else if (inject_delta > 0) {
        inject_delta = 0;
        __atomic_fetch_add(refs, 1u, __ATOMIC_RELAXED);
    }
    return __atomic_compare_exchange_n(refs, expected, desired, 0,
        __ATOMIC_RELEASE, __ATOMIC_RELAXED);
}
''' + leaf + '''
static int check(unsigned int initial, int injection, int expected_error,
    unsigned int expected_value, int expected_attempts)
{
    refcount_t ref;
    int error;
    __atomic_store_n(&ref.refs, initial, __ATOMIC_RELAXED);
    inject_delta = injection;
    attempts = destructor_calls = 0;
    error = lsf_cleanup_provider_ref_put_nonfinal(&ref);
    return error == expected_error && atomic_read(&ref.refs) == expected_value &&
        attempts == expected_attempts && !destructor_calls;
}
int main(void)
{
    refcount_t ref;
    if (!check(1u, 0, -EOPNOTSUPP, 1u, 0)) return 1;
    if (!check(2u, -1, -EOPNOTSUPP, 1u, 1)) return 2;
    if (!check(2u, 0, 0, 1u, 1)) return 3;
    if (!check(3u, -1, 0, 1u, 2)) return 4;
    if (!check(0u, 0, -EIO, 0u, 0)) return 5;
    if (!check(REFCOUNT_SATURATED, 0, -EOVERFLOW, REFCOUNT_SATURATED, 0)) return 6;
    if (!check(2u, 1, 0, 2u, 2)) return 7;
    /* Own nonfinal CAS wins; remaining external owner alone performs final. */
    __atomic_store_n(&ref.refs, 2u, __ATOMIC_RELAXED);
    inject_delta = attempts = destructor_calls = 0;
    if (lsf_cleanup_provider_ref_put_nonfinal(&ref) || destructor_calls ||
        atomic_read(&ref.refs) != 1u) return 8;
    external_put(&ref.refs);
    if (destructor_calls != 1 || atomic_read(&ref.refs) != 0u) return 9;
    /* A get after final-ref refusal does not consume our retained reference. */
    __atomic_store_n(&ref.refs, 1u, __ATOMIC_RELAXED);
    inject_delta = attempts = destructor_calls = 0;
    if (lsf_cleanup_provider_ref_put_nonfinal(&ref) != -EOPNOTSUPP) return 10;
    __atomic_fetch_add(&ref.refs, 1u, __ATOMIC_RELAXED);
    if (attempts || destructor_calls || atomic_read(&ref.refs) != 2u) return 11;
    /* A get before the actual observation permits normal real nonfinal put. */
    if (lsf_cleanup_provider_ref_put_nonfinal(&ref) ||
        atomic_read(&ref.refs) != 1u || destructor_calls) return 12;
    return 0;
}
''').encode()
