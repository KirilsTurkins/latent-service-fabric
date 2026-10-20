/* SPDX-License-Identifier: GPL-2.0-only */
/* Actual private hooks and unchanged upstream cookie chain, with explicit
 * C atomic/per-CPU/preemption/lock/type doubles. No trusted kernel proof. */
#ifdef LSF_FREESTANDING_REFERENCE
#include "reference-io.h"
#else
#ifdef NDEBUG
#undef NDEBUG
#endif
#include <assert.h>
#include <stdio.h>
#include <string.h>
#endif
#include <stdint.h>
typedef uint64_t u64;
typedef int64_t s64;
typedef uint64_t atomic64_t;
typedef int local_t;
struct sock { atomic64_t sk_cookie; };
#define __percpu
#define __aligned(value) __attribute__((aligned(value)))
#define ____cacheline_aligned_in_smp
#define DEFINE_PER_CPU(type, name) type name
#define ATOMIC64_INIT(value) (value)
#define this_cpu_ptr(pointer) (pointer)
#define likely(value) (value)
#define unlikely(value) (value)
#define __is_defined(name) 1
#ifndef __always_inline
#define __always_inline inline
#endif
static unsigned int model_lock_depth, preemption_depth, cookie_calls, inject_race, invalidate;
static u64 competing_cookie, last_compare_return;
static u64 model_competing_cookie(void);
static void model_preempt(void);
static int local_inc_return(local_t *value) { return ++*value; }
static void local_dec(local_t *value) { --*value; }
static s64 atomic64_add_return(s64 amount, atomic64_t *value) { *value += (u64)amount; return (s64)*value; }
static u64 atomic64_dec_return(atomic64_t *value) { return --*value; }
static u64 atomic64_read(const atomic64_t *value) { return *value; }
static u64 atomic64_cmpxchg(atomic64_t *value, u64 before, u64 after)
{
    u64 original;
    if (inject_race) {
        inject_race = 0;
        competing_cookie = model_competing_cookie();
        *value = competing_cookie;
    }
    original = *value;
    if (original == before) {
        *value = after;
    }
    last_compare_return = original;
    return original;
}
static void preempt_disable(void)
{
    assert(!model_lock_depth);
    model_preempt();
    ++preemption_depth;
    ++cookie_calls;
}
static void preempt_enable(void) { assert(preemption_depth == 1); --preemption_depth; }
static void model_lock(int *lock, unsigned long *flags)
{
    (void)lock; *flags = 0;
    assert(!model_lock_depth);
    ++model_lock_depth;
}
static void model_unlock(int *lock, unsigned long flags)
{
    (void)lock; (void)flags;
    assert(model_lock_depth == 1);
    --model_lock_depth;
}
#define CONFIG_LSF_STREAM_LINEAGE 1
#include "actual-cookie-functions.h"
/* Generated unchanged candidate translation unit; the old mode omits only
 * the newly added handoff module. The trusted constructor gate still refuses. */
#include "selected-kernel-lineage.c"

static struct lsf_key key;
static const struct lsf_scope scope = {{1, 2, 3, 4, 5, 6, 7, 8}};
static void model_preempt(void)
{
    if (invalidate) {
        lsf_stream_state.owners[key.slot].poisoned = 1;
        invalidate = 0;
    }
}
static u64 model_competing_cookie(void) { return gen_cookie_next(&sock_cookie); }

static struct lsf_bundle reserve(struct sock *sk)
{
    struct lsf_bundle bundle;
    struct lsf_admission admission;
    struct lsf_allocation_cost cost = {LSF_SOCKET, 512};
    memset(&lsf_stream_state, 0, sizeof(lsf_stream_state));
    lsf_stream_state.next_owner = lsf_stream_state.next_allocation = 1;
    assert(lsf_owner_admit(&lsf_stream_state, scope, LSF_TCP_BYTES, &key));
    assert(lsf_admission_capture(&lsf_stream_state, key, scope, &admission));
    assert(lsf_bundle_prepare(&lsf_stream_state, admission, lsf_empty_token(),
        LSF_CONSTRUCT_SOCKET, &cost, 1, &bundle));
    sk->sk_cookie = 0; /* Model the original __GFP_ZERO allocation, not a reset hook. */
    memset(&__sock_cookie, 0, sizeof(__sock_cookie));
    sock_cookie.forward_last = sock_cookie.reverse_last = 0;
    model_lock_depth = preemption_depth = cookie_calls = inject_race = invalidate = 0;
    return bundle;
}
#ifndef LSF_OLD_REFERENCE
static struct lsf_handoff capture(struct sock *sk)
{
    struct lsf_handoff handoff;
    assert(lsf_socket_capture_handoff(&lsf_stream_state, (u64)(uintptr_t)sk, &handoff));
    return handoff;
}
static void pass(const char *name) { puts(name); }
#endif

int main(void)
{
    struct sock sk;
    struct lsf_bundle bundle = reserve(&sk);
#ifdef LSF_OLD_REFERENCE
    /* Exact previous constructor callback, called with its actual selected
     * pre-initialization cookie0 argument. No allocator data is inspected. */
    lsf_stream_constructor_observed(&bundle, 0, &sk, 0);
    if (lsf_stream_state.allocations[bundle.tokens[0].slot].phase != LSF_LIVE) {
        fputs("HANDOFF_OLD_PREINITIALIZATION_COOKIE_CANNOT_COMMIT\n", stderr);
        return 2;
    }
    return 1;
#else
    struct lsf_handoff handoff, duplicate;
    struct lsf_bundle second;
    struct lsf_key foreign_key;
    struct lsf_admission admission, foreign;
    struct lsf_scope changed;
    struct lsf_token free_token;
    struct lsf_allocation_cost cost = {LSF_SOCKET, 512};
    struct sock child;
    u64 original_cookie, original_generation;
    unsigned int i;

    lsf_stream_socket_reserved(&bundle, &sk);
    assert(!sk.sk_cookie && lsf_stream_state.owners[key.slot].live_bytes == 512);
    assert(lsf_stream_state.allocations[bundle.tokens[0].slot].phase == LSF_RESERVED);
    lsf_stream_socket_initialized(&sk);
    assert(sk.sk_cookie && cookie_calls == 1 && !preemption_depth && !model_lock_depth);
    assert(lsf_stream_state.allocations[bundle.tokens[0].slot].phase == LSF_LIVE);
    assert(lsf_stream_state.owners[key.slot].live_bytes == 512 && !lsf_stream_state.poisoned);
    pass("HANDOFF_CONTROL actual-hooks-use-upstream-cookie-after-reserved-address PASS");

    bundle = reserve(&sk);
    lsf_stream_socket_reserved(&bundle, &sk);
    assert(lsf_begin_drain(&lsf_stream_state, key));
    assert(!lsf_mechanism_drained(&lsf_stream_state, key));
    lsf_stream_socket_initialized(&sk);
    assert(lsf_stream_state.allocations[bundle.tokens[0].slot].phase == LSF_LIVE);
    assert(!lsf_mechanism_drained(&lsf_stream_state, key));
    free_token = lsf_stream_before_free(LSF_SOCKET, &sk, sk.sk_cookie);
    assert(free_token.generation && lsf_stream_state.owners[key.slot].live_bytes == 512);
    lsf_stream_after_free(free_token);
    assert(lsf_mechanism_drained(&lsf_stream_state, key));
    pass("HANDOFF_CONTROL original-charge-survives-drain-and-only-model-postfree-retires PASS");

    bundle = reserve(&sk);
    lsf_stream_socket_reserved(&bundle, &sk);
    handoff = capture(&sk); duplicate = handoff;
    original_cookie = sock_gen_cookie(&sk);
    assert(lsf_socket_commit_handoff(&lsf_stream_state, &handoff, (u64)(uintptr_t)&sk, original_cookie));
    assert(!lsf_socket_commit_handoff(&lsf_stream_state, &duplicate, (u64)(uintptr_t)&sk, original_cookie));
    assert(lsf_stream_state.poisoned && lsf_stream_state.owners[key.slot].live_bytes == 512);
    pass("HANDOFF_CONTROL copied-handoff-cannot-commit-twice PASS");

    for (i = 0; i < 8; ++i) {
        bundle = reserve(&sk);
        lsf_stream_socket_reserved(&bundle, &sk);
        handoff = capture(&sk);
        handoff.admission.scope.identity[i]++;
        assert(!lsf_socket_commit_handoff(&lsf_stream_state, &handoff,
            (u64)(uintptr_t)&sk, sock_gen_cookie(&sk)));
        assert(lsf_stream_state.poisoned && lsf_stream_state.owners[key.slot].live_bytes == 512);
    }
    pass("HANDOFF_CONTROL all-eight-original-scope-words-revalidated PASS");

    bundle = reserve(&sk);
    lsf_stream_socket_reserved(&bundle, &sk);
    handoff = capture(&sk); duplicate = handoff;
    original_generation = handoff.token.generation;
    original_cookie = sock_gen_cookie(&sk);
    assert(lsf_socket_commit_handoff(&lsf_stream_state, &handoff, (u64)(uintptr_t)&sk, original_cookie));
    free_token = lsf_stream_before_free(LSF_SOCKET, &sk, original_cookie);
    lsf_stream_after_free(free_token);
    assert(lsf_admission_capture(&lsf_stream_state, key, scope, &admission));
    assert(lsf_bundle_prepare(&lsf_stream_state, admission, lsf_empty_token(),
        LSF_CONSTRUCT_SOCKET, &cost, 1, &second));
    lsf_stream_socket_reserved(&second, &sk);
    assert(second.tokens[0].generation != original_generation);
    assert(!lsf_socket_commit_handoff(&lsf_stream_state, &duplicate,
        (u64)(uintptr_t)&sk, original_cookie));
    assert(lsf_stream_state.owners[key.slot].live_bytes == 512);
    pass("HANDOFF_CONTROL old-generation-cannot-commit-reused-address PASS");

    bundle = reserve(&sk);
    lsf_stream_socket_reserved(&bundle, &sk);
    handoff = capture(&sk);
    changed = scope; changed.identity[0] = 9;
    assert(lsf_owner_admit(&lsf_stream_state, changed, LSF_TCP_BYTES, &foreign_key));
    assert(lsf_admission_capture(&lsf_stream_state, foreign_key, changed, &foreign));
    handoff.admission = foreign;
    assert(!lsf_socket_commit_handoff(&lsf_stream_state, &handoff,
        (u64)(uintptr_t)&sk, sock_gen_cookie(&sk)));
    assert(lsf_stream_state.owners[key.slot].live_bytes == 512 &&
           !lsf_stream_state.owners[foreign_key.slot].live_bytes);
    pass("HANDOFF_CONTROL foreign-owner-generation-cannot-adopt-pending-socket PASS");

    bundle = reserve(&sk);
    lsf_stream_socket_reserved(&bundle, &sk);
    free_token = lsf_stream_before_free(LSF_SOCKET, &sk, 0);
    assert(!free_token.generation && lsf_stream_state.owners[key.slot].poisoned);
    lsf_stream_after_free(free_token);
    assert(lsf_stream_state.owners[key.slot].live_bytes == 512 && !cookie_calls);
    pass("HANDOFF_CONTROL early-constructor-destruction-retains-uninitialized-charge PASS");

    bundle = reserve(&sk);
    original_cookie = sock_gen_cookie(&sk);
    lsf_stream_socket_reserved(&bundle, &sk);
    lsf_stream_socket_initialized(&sk);
    assert(sk.sk_cookie == original_cookie);
    child.sk_cookie = sk.sk_cookie; /* Exact existing sock_copy prefix semantics. */
    assert(lsf_admission_capture(&lsf_stream_state, key, scope, &admission));
    assert(lsf_bundle_prepare(&lsf_stream_state, admission, lsf_empty_token(),
        LSF_CONSTRUCT_SOCKET, &cost, 1, &second));
    lsf_stream_socket_reserved(&second, &child);
    lsf_stream_socket_initialized(&child);
    assert(child.sk_cookie == original_cookie && second.tokens[0].generation != bundle.tokens[0].generation);
    assert(lsf_stream_state.owners[key.slot].live_bytes == 1024 && !lsf_stream_state.poisoned);
    pass("HANDOFF_CONTROL legitimate-inherited-cookie-is-preserved-not-reset PASS");

    bundle = reserve(&sk);
    lsf_stream_socket_reserved(&bundle, &sk);
    inject_race = 1;
    lsf_stream_socket_initialized(&sk);
    original_cookie = lsf_stream_state.allocations[bundle.tokens[0].slot].token.cookie;
    assert(competing_cookie && original_cookie == sk.sk_cookie &&
           sk.sk_cookie == competing_cookie && last_compare_return == competing_cookie);
    assert(sock_gen_cookie(&sk) == competing_cookie && !lsf_stream_state.poisoned);
    assert(!preemption_depth && !model_lock_depth);
    pass("HANDOFF_CONTROL unchanged-upstream-compare-exchange-keeps-competing-winner PASS");

    bundle = reserve(&sk);
    lsf_stream_socket_reserved(&bundle, &sk);
    invalidate = 1;
    lsf_stream_socket_initialized(&sk);
    assert(lsf_stream_state.poisoned && lsf_stream_state.owners[key.slot].live_bytes == 512);
    assert(lsf_stream_state.allocations[bundle.tokens[0].slot].phase == LSF_RESERVED);
    pass("HANDOFF_CONTROL invalidation-between-capture-and-cookie-retains-reservation PASS");

    bundle = reserve(&sk);
    lsf_stream_socket_reserved(&bundle, &sk);
    assert(lsf_admission_capture(&lsf_stream_state, key, scope, &admission));
    assert(lsf_bundle_prepare(&lsf_stream_state, admission, lsf_empty_token(),
        LSF_CONSTRUCT_SOCKET, &cost, 1, &second));
    lsf_stream_socket_reserved(&second, &sk);
    assert(lsf_stream_state.poisoned && !cookie_calls && lsf_stream_state.owners[key.slot].live_bytes == 1024);
    pass("HANDOFF_CONTROL address-collision-before-initialization-does-not-transfer-credit PASS");

    bundle = reserve(&sk);
    lsf_stream_socket_reserved(&bundle, &sk);
    handoff = capture(&sk);
    assert(!lsf_socket_commit_handoff(&lsf_stream_state, &handoff,
        (u64)(uintptr_t)&child, sock_gen_cookie(&sk)));
    assert(lsf_stream_state.poisoned && lsf_stream_state.owners[key.slot].live_bytes == 512);
    pass("HANDOFF_CONTROL wrong-initialized-object-cannot-consume-ticket PASS");

    bundle = reserve(&sk);
    lsf_stream_socket_initialized(&sk);
    assert(lsf_stream_state.poisoned && !cookie_calls && lsf_stream_state.owners[key.slot].live_bytes == 512);
    memset(&lsf_stream_state, 0, sizeof(lsf_stream_state));
    lsf_stream_state.next_owner = lsf_stream_state.next_allocation = 1;
    lsf_stream_socket_initialized(&sk);
    assert(!lsf_stream_state.poisoned && !cookie_calls);
    pass("HANDOFF_CONTROL unknown-initialization-never-reads-cookie-or-certifies-absence PASS");

    bundle = reserve(&sk);
    assert(!lsf_stream_constructor_prepare(LSF_CONSTRUCT_SOCKET, 0, 0, 0, 0, 0, &second));
    assert(lsf_stream_state.owners[key.slot].live_bytes == 512 && !cookie_calls);
    pass("HANDOFF_CONTROL actual-trusted-factory-gate-remains-closed PASS");
    puts("HANDOFF_SUMMARY 14 PASS; linux-executed=false; trusted-factory=false; final-free-certified=false");
    return 0;
#endif
}
