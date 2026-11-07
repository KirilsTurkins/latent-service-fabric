/* Host syntax control only; the component build generates the real binding. */
#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
typedef struct { uint8_t *ptr; size_t len; } probe_string_t;
void probe_string_free(probe_string_t *);
void probe_string_dup(probe_string_t *, const char *);
