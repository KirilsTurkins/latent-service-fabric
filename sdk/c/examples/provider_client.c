#include "common.h"

#include <stdio.h>

int main(int argc, char **argv) {
    ex_config config;
    if (!ex_config_load(&config, argc, argv)) {
        ex_config_close(&config);
        fputs("{\"stage\":\"configuration\",\"reason\":\"private-input\"}\n", stderr);
        return 1;
    }
    latent_transport *client = ex_client(&config, false, false, false);
    bool passed = client != NULL;
    const char *const suffixes[] = {"example-http", "example-blob"};
    const uint64_t values[] = {2201, 4};
    for (unsigned index = 0; passed && index < 2; ++index) {
        ex_result result = {0};
        latent_profile_call *call = ex_invoke(&config, client, index, suffixes[index], NULL, false, 5000, &result);
        passed = ex_wait(client, &result, ex_now() + 6000) && ex_guest(&result, values[index]);
        latent_transport_profile_vtable()->release_call(call);
    }
    if (!ex_close(&client)) passed = false;
    ex_config_close(&config);
    if (!passed) {
        fputs("{\"stage\":\"provider-client\",\"reason\":\"guest-workflow\"}\n", stderr);
        return 1;
    }
    puts("{\"http\":\"2201\",\"blob\":\"4\"}");
    return 0;
}
