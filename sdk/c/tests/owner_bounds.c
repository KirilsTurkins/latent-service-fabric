#include "internal.h"
#include "nghttp2_callbacks.h"
#include "nghttp2_option.h"

#include <stdio.h>

int main(void) {
    printf("C owner layout: owner=%zu call=%zu; fixed nghttp2 initialization allocations=%zu+%zu bytes\n",
           sizeof(latent_transport), sizeof(latent_profile_call),
           sizeof(nghttp2_session_callbacks), sizeof(nghttp2_option));
    return 0;
}
