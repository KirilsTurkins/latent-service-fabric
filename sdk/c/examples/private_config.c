#include "common.h"

#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

typedef struct json_node {
    latent_string text;
    size_t next;
    bool object;
} json_node;

typedef struct json_input {
    char *data;
    size_t length;
    size_t position;
    json_node nodes[128];
    size_t used;
} json_input;

static void whitespace(json_input *input) {
    while (input->position < input->length) {
        char value = input->data[input->position];
        if (value != ' ' && value != '\n' && value != '\r' && value != '\t') break;
        ++input->position;
    }
}

static bool unicode_unit(json_input *input, uint32_t *code) {
    if (input->length - input->position < 4) return false;
    uint32_t number = 0;
    for (unsigned index = 0; index < 4; ++index) {
        unsigned char digit = (unsigned char)input->data[input->position++];
        unsigned amount;
        if (digit >= '0' && digit <= '9') amount = digit - '0';
        else if (digit >= 'a' && digit <= 'f') amount = digit - 'a' + 10;
        else if (digit >= 'A' && digit <= 'F') amount = digit - 'A' + 10;
        else return false;
        number = (number << 4) | amount;
    }
    *code = number;
    return true;
}

static bool string(json_input *input, latent_string *output) {
    if (input->position >= input->length || input->data[input->position++] != '"') return false;
    size_t start = input->position;
    size_t written = start;
    while (input->position < input->length) {
        unsigned char value = (unsigned char)input->data[input->position++];
        if (value == '"') {
            input->data[written] = 0;
            *output = (latent_string){input->data + start, written - start};
            return output->length <= 4096;
        }
        if (value < 0x20) return false;
        if (value == '\\') {
            if (input->position >= input->length) return false;
            value = (unsigned char)input->data[input->position++];
            if (value == 'u') {
                uint32_t code;
                if (!unicode_unit(input, &code) || code == 0) return false;
                if (code >= 0xd800 && code <= 0xdbff) {
                    if (input->length - input->position < 6 || input->data[input->position++] != '\\'
                        || input->data[input->position++] != 'u') return false;
                    uint32_t low;
                    if (!unicode_unit(input, &low) || low < 0xdc00 || low > 0xdfff) return false;
                    code = 0x10000 + ((code - 0xd800) << 10) + low - 0xdc00;
                } else if (code >= 0xdc00 && code <= 0xdfff) return false;
                if (code < 0x80) input->data[written++] = (char)code;
                else if (code < 0x800) {
                    input->data[written++] = (char)(0xc0 | (code >> 6));
                    input->data[written++] = (char)(0x80 | (code & 63));
                } else if (code < 0x10000) {
                    input->data[written++] = (char)(0xe0 | (code >> 12));
                    input->data[written++] = (char)(0x80 | ((code >> 6) & 63));
                    input->data[written++] = (char)(0x80 | (code & 63));
                } else {
                    input->data[written++] = (char)(0xf0 | (code >> 18));
                    input->data[written++] = (char)(0x80 | ((code >> 12) & 63));
                    input->data[written++] = (char)(0x80 | ((code >> 6) & 63));
                    input->data[written++] = (char)(0x80 | (code & 63));
                }
                continue;
            }
            if (value == 'n') value = '\n';
            else if (value == 'r') value = '\r';
            else if (value == 't') value = '\t';
            else if (value == 'b') value = '\b';
            else if (value == 'f') value = '\f';
            else if (value != '"' && value != '\\' && value != '/') return false;
        }
        input->data[written++] = (char)value;
    }
    return false;
}

static bool parse(json_input *input, unsigned depth) {
    whitespace(input);
    if (depth > 8 || input->used >= 128 || input->position >= input->length) return false;
    size_t node = input->used++;
    if (input->data[input->position] == '"') {
        if (!string(input, &input->nodes[node].text)) return false;
        input->nodes[node].next = input->used;
        return true;
    }
    if (input->data[input->position++] != '{') return false;
    input->nodes[node].object = true;
    whitespace(input);
    if (input->position < input->length && input->data[input->position] == '}') ++input->position;
    else {
        for (;;) {
            size_t key = input->used;
            if (!parse(input, depth + 1) || input->nodes[key].object) return false;
            for (size_t previous = node + 1; previous < key; previous = input->nodes[previous + 1].next) {
                latent_string first = input->nodes[previous].text, second = input->nodes[key].text;
                if (first.length == second.length && memcmp(first.data, second.data, first.length) == 0) return false;
            }
            whitespace(input);
            if (input->position >= input->length || input->data[input->position++] != ':' || !parse(input, depth + 1)) return false;
            whitespace(input);
            if (input->position >= input->length) return false;
            char separator = input->data[input->position++];
            if (separator == '}') break;
            if (separator != ',') return false;
        }
    }
    input->nodes[node].next = input->used;
    return true;
}

static size_t member(const json_input *input, size_t object, const char *name) {
    if (object >= input->used || !input->nodes[object].object) return SIZE_MAX;
    for (size_t index = object + 1; index < input->nodes[object].next; index = input->nodes[index + 1].next) {
        latent_string key = input->nodes[index].text;
        if (key.length == strlen(name) && memcmp(key.data, name, key.length) == 0) return index + 1;
    }
    return SIZE_MAX;
}

static latent_string field(const json_input *input, size_t object, const char *name) {
    size_t index = member(input, object, name);
    return index == SIZE_MAX || input->nodes[index].object ? (latent_string){0} : input->nodes[index].text;
}

static bool text_equal(latent_string value, const char *expected) {
    return value.length == strlen(expected) && value.data != NULL && memcmp(value.data, expected, value.length) == 0;
}

static int directory(const char *path) {
    int descriptor = open(path, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
    struct stat status;
    if (descriptor < 0) return -1;
    if (fstat(descriptor, &status) != 0 || !S_ISDIR(status.st_mode) || status.st_uid != geteuid()
        || (status.st_mode & 077) != 0) { close(descriptor); return -1; }
    return descriptor;
}

static bool protected_read(const char *path, uint8_t *buffer, size_t maximum, size_t *length, bool secret) {
    if (path == NULL || path[0] != '/' || strlen(path) >= 4096) return false;
    char parent[4096];
    memcpy(parent, path, strlen(path) + 1);
    char *last = strrchr(parent, '/');
    if (last == NULL || last == parent || last[1] == 0) return false;
    *last = 0;
    int root = directory(parent);
    if (root < 0) return false;
    int descriptor = openat(root, last + 1, O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC);
    close(root);
    if (descriptor < 0) return false;
    struct stat status;
    bool valid = fstat(descriptor, &status) == 0 && S_ISREG(status.st_mode) && status.st_uid == geteuid()
        && status.st_nlink == 1 && (status.st_mode & (secret ? 077 : 022)) == 0
        && status.st_size > 0 && (uint64_t)status.st_size <= maximum;
    size_t used = 0;
    while (valid && used <= maximum) {
        ssize_t amount = read(descriptor, buffer + used, maximum + 1 - used);
        if (amount < 0 && errno == EINTR) continue;
        if (amount < 0) { valid = false; break; }
        if (amount == 0) break;
        used += (size_t)amount;
    }
    close(descriptor);
    if (!valid || used > maximum || used != (size_t)status.st_size) return false;
    buffer[used] = 0;
    *length = used;
    return true;
}

bool ex_config_load(ex_config *config, int argc, char **argv) {
    memset(config, 0, sizeof(*config));
    config->control_fd = -1;
    if (argc != 3 || strcmp(argv[1], "--config") != 0) return false;
    size_t length;
    if (!protected_read(argv[2], (uint8_t *)config->input, 16384, &length, false)) return false;
    json_input input = {.data = config->input, .length = length};
    if (!parse(&input, 0)) return false;
    whitespace(&input);
    if (input.position != length || !text_equal(field(&input, 0, "schemaVersion"), "latent.sdk.provider.workflow.input.v1")
        || !text_equal(field(&input, 0, "language"), "c") || !text_equal(field(&input, 0, "tenant"), "tests")) return false;
    config->endpoint = field(&input, 0, "endpoint");
    config->tenant = field(&input, 0, "tenant");
    config->upstream_url = field(&input, 0, "upstreamUrl");
    config->policy_document = field(&input, 0, "policyDocument");
    if (config->endpoint.length == 0 || config->upstream_url.length == 0 || config->policy_document.length == 0) return false;
    latent_string credential = field(&input, 0, "credentialFile");
    if (!protected_read(credential.data, config->credential, 256, &config->credential_length, true)) return false;
    latent_string control = field(&input, 0, "controlDirectory");
    if (control.length == 0 || control.data[0] != '/') return false;
    config->control_fd = directory(control.data);
    if (config->control_fd < 0) return false;
    size_t targets = member(&input, 0, "targets");
    const char *const names[] = {"http", "blob", "callee"};
    for (unsigned index = 0; index < 3; ++index) {
        size_t target = member(&input, targets, names[index]);
        ex_target *selected = &config->targets[index];
        selected->service = field(&input, target, "service");
        selected->route = field(&input, target, "route");
        selected->contract = field(&input, target, "contract");
        selected->function = field(&input, target, "function");
        selected->publication = field(&input, target, "publication");
        selected->component_digest = field(&input, target, "componentDigest");
        if (selected->service.length == 0 || selected->route.length == 0 || selected->contract.length == 0
            || selected->function.length == 0 || selected->publication.length == 0 || selected->component_digest.length == 0) return false;
    }
    return true;
}

void ex_config_close(ex_config *config) {
    if (config->control_fd >= 0) close(config->control_fd);
    config->control_fd = -1;
    volatile uint8_t *bytes = config->credential;
    for (size_t index = 0; index < sizeof(config->credential); ++index) bytes[index] = 0;
}

bool ex_mode(ex_config *config, const char *value) {
    size_t length = strlen(value);
    if (length == 0 || length > 64) return false;
    int descriptor = openat(config->control_fd, "c-mode.tmp", O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
    if (descriptor < 0) return false;
    ssize_t written = write(descriptor, value, length);
    int closed = close(descriptor);
    bool valid = written == (ssize_t)length && closed == 0;
    if (valid) valid = renameat(config->control_fd, "c-mode.tmp", config->control_fd, "mode") == 0;
    if (!valid) (void)unlinkat(config->control_fd, "c-mode.tmp", 0);
    return valid;
}

bool ex_marker(ex_config *config, const char *prefix, const char *token) {
    char name[96];
    int length = snprintf(name, sizeof(name), "%s-%s", prefix, token);
    if (length <= 0 || (size_t)length >= sizeof(name)) return false;
    struct stat status;
    return fstatat(config->control_fd, name, &status, AT_SYMLINK_NOFOLLOW) == 0
        && S_ISREG(status.st_mode) && status.st_uid == geteuid();
}
