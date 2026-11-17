/* Ordinary stdin use must not acquire an ambient Preview 1 provider. */
#include "probe.h"
#include <stdio.h>

bool exports_examples_greeting_api_greet(probe_string_t *name, probe_string_t *value,
                                        probe_string_t *error) {
    (void)error;
    char data[8];
    size_t count = fread(data, 1, sizeof(data), stdin);
    probe_string_free(name);
    probe_string_dup(value, count ? "input" : "empty");
    return true;
}
