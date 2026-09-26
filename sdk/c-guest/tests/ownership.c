/* SPDX-License-Identifier: Apache-2.0 */
#include "lsf/ownership.h"
#include <assert.h>

static unsigned closed[LSF_SCOPE_CAPACITY], count;
static void close_owner(void *value) { closed[count++] = *(unsigned *)value; }

int main(void) {
    lsf_scope_t scope;
    lsf_scope_init(&scope, 8);
    assert(!lsf_scope_alloc(&scope, SIZE_MAX, 2));
    assert(!lsf_scope_alloc(&scope, 9, 1));
    void *bytes = lsf_scope_alloc(&scope, 8, 1);
    assert(bytes && scope.live == 8 && scope.peak == 8);
    assert(!lsf_scope_alloc(&scope, 1, 1));
    assert(!lsf_scope_adopt(&scope, bytes, 0, free));
    assert(lsf_scope_detach(&scope, bytes));
    assert(!lsf_scope_detach(&scope, bytes));
    lsf_scope_close(&scope);
    free(bytes); /* sole owner after transfer */
    unsigned owners[LSF_SCOPE_CAPACITY + 1];
    lsf_scope_init(&scope, sizeof(owners));
    for (unsigned i = 0; i < LSF_SCOPE_CAPACITY + 1; ++i) owners[i] = i;
    for (unsigned i = 0; i < LSF_SCOPE_CAPACITY; ++i)
        assert(lsf_scope_adopt(&scope, &owners[i], sizeof(unsigned), close_owner));
    assert(!lsf_scope_adopt(&scope, &owners[LSF_SCOPE_CAPACITY], 0, close_owner));
    assert(lsf_scope_release(&scope, &owners[0]));
    assert(!lsf_scope_release(&scope, &owners[0]));
    lsf_scope_close(&scope);
    lsf_scope_close(&scope);
    assert(count == LSF_SCOPE_CAPACITY && closed[0] == 0);
    for (unsigned i = 1; i < LSF_SCOPE_CAPACITY; ++i)
        assert(closed[i] == LSF_SCOPE_CAPACITY - i);
    assert(scope.live == 0 && scope.count == 0);
    unsigned char secret[] = {1, 2, 3};
    lsf_zeroize(secret, sizeof(secret));
    assert(!secret[0] && !secret[1] && !secret[2]);
    return 0;
}
