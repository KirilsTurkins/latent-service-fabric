from __future__ import annotations

import json
from pathlib import Path
import re
import sys


SDK = Path(__file__).resolve().parents[1]
ROOT = SDK.parents[1]


def main():
    destination = Path(sys.argv[1])
    profile = json.loads((ROOT / "sdk/profile/client-profile.json").read_text())
    names = {}
    for path, selected in profile["sources"].items():
        package = re.search(r"package\s+([\w.]+)", (ROOT / path).read_text()).group(1)
        for name in selected:
            native = "latent_profile_" + re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()
            names[native] = "lsf_" + package.replace(".", "_") + "_" + name
    lines = ['#include "wire_generated.h"', "#include <stdio.h>"]
    active = False
    count = 0
    source = (SDK / "tests/profile_vectors.h").read_text().splitlines()
    for index, line in enumerate(source):
        if line == "    }" and active:
            lines.append("        lsf_arena_clear(&arena);")
            active = False
        lines.append(line)
        match = re.match(r"        (latent_profile_\w+) value = ", line)
        if match and match.group(1) in names:
            native = match.group(1)
            symbol = names[native]
            nearby = "\n".join(source[index:index + 3])
            contradictory = "contradictory" in nearby
            lines.extend(["        uint8_t encoded[65536];", "        size_t length = 0;",
                          "        lsf_arena arena = {.maximum = 1048576};", "        bool limit = false;"])
            if contradictory:
                lines.extend([f"        assert(!lsf_encode(&{symbol}, &value, encoded, sizeof(encoded), &length, UINT64_MAX, NULL));",
                              "        (void)limit;"])
            else:
                lines.extend([f"        assert(lsf_encode(&{symbol}, &value, encoded, sizeof(encoded), &length, UINT64_MAX, NULL));",
                              "        memset(&value, 0, sizeof(value));",
                              f"        assert(lsf_decode(&{symbol}, encoded, length, &value, &arena, UINT64_MAX, &limit));"])
            active = True
            count += 1
    lines.extend(["int main(void) {", "    profile_vectors();",
                  f'    puts("C native protobuf round trips: {count} shared wire vectors; all semantic assertions retained");',
                  "    return 0;", "}"])
    (destination / "wire_vectors.c").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
