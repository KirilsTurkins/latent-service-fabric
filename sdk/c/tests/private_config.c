#include "../examples/common.h"

#include <assert.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static void write_file(const char *path, const char *body, mode_t mode) {
    int descriptor = open(path, O_WRONLY | O_CREAT | O_TRUNC | O_NOFOLLOW, mode);
    assert(descriptor >= 0);
    assert(write(descriptor, body, strlen(body)) == (ssize_t)strlen(body));
    assert(close(descriptor) == 0);
    assert(chmod(path, mode) == 0);
}

int main(void) {
    char directory[] = "/tmp/latent-c-config-XXXXXX";
    assert(mkdtemp(directory) != NULL);
    char path[128], credential[128], link[128], body[4096];
    assert(snprintf(path, sizeof(path), "%s/input.json", directory) > 0);
    assert(snprintf(credential, sizeof(credential), "%s/token", directory) > 0);
    assert(snprintf(link, sizeof(link), "%s/link", directory) > 0);
    const char *target = "{\"service\":\"test\",\"route\":\"test\",\"contract\":\"test\",\"function\":\"run\",\"publication\":\"test\",\"componentDigest\":\"test\"}";
    int length = snprintf(body, sizeof(body), "{\"schemaVersion\":\"latent.sdk.provider.workflow.input.v1\",\"language\":\"c\","
        "\"tenant\":\"tests\",\"endpoint\":\"http://127.0.0.1:1\",\"upstreamUrl\":\"http://localhost:1/allowed\","
        "\"policyDocument\":\"{\\\"rules\\\":[]}\",\"credentialFile\":\"%s\",\"controlDirectory\":\"%s\","
        "\"targets\":{\"http\":%s,\"blob\":%s,\"callee\":%s}}", credential, directory, target, target, target);
    assert(length > 0 && (size_t)length < sizeof(body));
    write_file(path, body, 0600);
    write_file(credential, "LSF-PUBLIC-C-CONFIG-TEST-ONLY", 0600);
    char *arguments[] = {"private-config-tests", "--config", path};
    ex_config config;
    assert(ex_config_load(&config, 3, arguments));
    assert(config.credential_length == strlen("LSF-PUBLIC-C-CONFIG-TEST-ONLY"));
    assert(config.policy_document.length == strlen("{\"rules\":[]}"));
    assert(memcmp(config.policy_document.data, "{\"rules\":[]}", config.policy_document.length) == 0);
    ex_config_close(&config);
    for (size_t index = 0; index < sizeof(config.credential); ++index) assert(config.credential[index] == 0);
    assert(chmod(credential, 0644) == 0);
    assert(!ex_config_load(&config, 3, arguments));
    ex_config_close(&config);
    assert(chmod(credential, 0600) == 0);
    assert(chmod(directory, 0755) == 0);
    assert(!ex_config_load(&config, 3, arguments));
    ex_config_close(&config);
    assert(chmod(directory, 0700) == 0);
    assert(symlink(path, link) == 0);
    arguments[2] = link;
    assert(!ex_config_load(&config, 3, arguments));
    ex_config_close(&config);
    arguments[2] = path;
    const char *invalid[] = {"{\"language\":\"c\",\"language\":\"c\"}", "{\"a\":\"\\u0000\"}",
        "{\"a\":\"\\ud800\"}", "{\"a\":[]}", "{\"a\":\"unterminated}", "{}garbage"};
    for (size_t index = 0; index < sizeof(invalid) / sizeof(invalid[0]); ++index) {
        write_file(path, invalid[index], 0600);
        assert(!ex_config_load(&config, 3, arguments));
        ex_config_close(&config);
    }
    assert(unlink(path) == 0 && unlink(credential) == 0 && unlink(link) == 0 && rmdir(directory) == 0);
    puts("C private configuration: bounded parsing, file permissions, symlink rejection and credential wiping passed");
    return 0;
}
