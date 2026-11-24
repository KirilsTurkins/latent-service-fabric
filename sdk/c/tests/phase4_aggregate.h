#ifndef LSF_TEST_PHASE4_AGGREGATE_H
#define LSF_TEST_PHASE4_AGGREGATE_H

#include <latent/transaction_client.h>
#include <assert.h>
#include <stdlib.h>
#include <string.h>

static inline latent_string phase4_aggregate_service(void) {
    const char *service = getenv("LSF_401_AGGREGATE_SERVICE");
    if (!service) service = "examples/transaction-java-aggregate";
    return (latent_string){service, strlen(service)};
}

static inline latent_string phase4_aggregate_route(bool query) {
    const char *route = query ? getenv("LSF_401_AGGREGATE_QUERY_ROUTE") : NULL;
    if (!route) route = getenv("LSF_401_AGGREGATE_ROUTE");
    if (!route) route = "transaction-java-aggregate";
    return (latent_string){route, strlen(route)};
}

static inline uint64_t phase4_aggregate_command_wall_limit(void) {
    const char *value = getenv("LSF_401_COMMAND_WALL_TIME_MILLIS");
    if (!value) {
        return 120000;
    }
    const size_t length = strlen(value);
    assert(length > 0 && length <= 6 && strspn(value, "0123456789") == length);
    const unsigned long millis = strtoul(value, NULL, 10);
    assert(millis > 0 && millis <= 120000);
    return millis;
}

#endif
