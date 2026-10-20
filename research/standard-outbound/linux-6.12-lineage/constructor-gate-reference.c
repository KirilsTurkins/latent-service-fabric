/* SPDX-License-Identifier: GPL-2.0-only */
/* Compile the actual candidate gate/header with explicit spinlock/type doubles.
 * No Linux ABI, locking, allocation, installation or trusted factory is proven. */
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

#ifdef LSF_REFERENCE_SELECTED
#define CONFIG_LSF_STREAM_LINEAGE 1
#include "net/core/lsf_stream_lineage.c"
#else
#include <net/lsf_stream_constructors.h>
#endif

int main(void)
{
    struct lsf_bundle bundle = {0};
    unsigned int constructor;
#ifdef LSF_REFERENCE_SELECTED
    for (constructor = LSF_CONSTRUCT_SOCKET; constructor <= LSF_CONSTRUCT_FCLONE; ++constructor)
        assert(!lsf_stream_constructor_prepare(constructor, 0, 64, 0, 0, -1, &bundle));
    puts("GATE_CONTROL actual-candidate-unknown-refuses-all-constructor-shapes PASS");
    assert(lsf_stream_state.next_owner == 1 && lsf_stream_state.next_allocation == 1);
    assert(!lsf_stream_state.poisoned && !lsf_stream_state.owners[0].phase);
    puts("GATE_CONTROL refused-unknown-does-not-register-or-reserve-owner PASS");
    puts("GATE_SUMMARY 2 PASS; linux-executed=false; final-free-certified=false");
#else
    bundle.count = 19;
    for (constructor = LSF_CONSTRUCT_SOCKET; constructor <= LSF_CONSTRUCT_FCLONE; ++constructor) {
        assert(lsf_stream_constructor_prepare(constructor, 0, 64, 0, 0, -1, &bundle));
        lsf_stream_constructor_observed(&bundle, 0, 0, 0);
        lsf_stream_constructor_uncertain(&bundle);
    }
    assert(bundle.count == 19);
    puts("GATE_CONTROL unselected-header-preserves-original-path-without-state PASS");
    puts("GATE_SUMMARY 1 PASS; linux-executed=false; final-free-certified=false");
#endif
    return 0;
}
