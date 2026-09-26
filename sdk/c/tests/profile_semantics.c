/* Portable C11 profile models and callback ownership, without a transport. */
#include "latent/profile.h"

#include <stdio.h>

#include "profile_vectors.h"
#include "profile_lifetime.h"

int main(void) {
    profile_vectors();
    profile_lifetime();
    puts("C common profile semantics and callback lifetime passed");
    return 0;
}
