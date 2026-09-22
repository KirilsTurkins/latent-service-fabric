#ifndef LATENT_TYPES_H
#define LATENT_TYPES_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

typedef struct latent_bytes {
    const uint8_t *data;
    size_t length;
} latent_bytes;

typedef struct latent_string {
    const char *data;
    size_t length;
} latent_string;

typedef struct latent_key_value {
    latent_string key;
    latent_string value;
} latent_key_value;

#endif
