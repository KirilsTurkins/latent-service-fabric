"""Exercise ordinary Assembly lookup inside the signed greeting component."""
from __future__ import annotations

import base64
import json
from pathlib import Path

from tools.dev_workflow.common import digest, encode
from tools import guest_resources


def install(project: Path) -> dict:
    payloads = {
        "data/binary.bin": b"\x00\xff\xfe\x80\n",
        "data/alias.bin": b"\x00\xff\xfe\x80\n",
        "culture/fr.txt": b"Bonjour",
        "data/empty.bin": b"",
        "data/$(Unexpanded);snowman\u2603.txt": b"literal logical name",
    }
    rows = []
    assets = project / "assets"
    assets.mkdir()
    for index, (logical, payload) in enumerate(payloads.items()):
        source = "assets/resource-" + str(index) + ".bin"
        (project / source).write_bytes(payload)
        rows.append({"path": logical, "source": source, "mediaType": "application/octet-stream"})
    (project / "capsule-resources.json").write_bytes(encode({
        "schemaVersion": guest_resources.PROFILE, "resources": rows}))
    expected = ",\n".join("            [" + json.dumps(name, ensure_ascii=True) + "] = "
                           + json.dumps(base64.b64encode(payload).decode())
                           for name, payload in payloads.items())
    source = project / "src/Main.cs"
    before = source.read_bytes()
    hook = b"        string clean = Text.Trim(name);"
    if before.count(hook) != 1:
        raise ValueError("C# resource qualification source hook changed")
    source.write_bytes(before.replace(hook, b"        ResourceControls.Check();\n" + hook))
    helper = '''using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;

internal static class ResourceControls {
    internal static void Check() {
        var expected = new Dictionary<string, string> {
EXPECTED
        };
        var assembly = typeof(ResourceControls).Assembly;
        if (!assembly.GetManifestResourceNames().OrderBy(x => x, StringComparer.Ordinal)
            .SequenceEqual(expected.Keys.OrderBy(x => x, StringComparer.Ordinal)))
            throw new Exception("resource names differ");
        if (assembly.GetManifestResourceStream("missing") is not null)
            throw new Exception("absent resource found");
        for (var iteration = 0; iteration < 8; iteration++) {
            foreach (var item in expected) {
                using var first = assembly.GetManifestResourceStream(item.Key)
                    ?? throw new Exception("resource absent");
                using var second = assembly.GetManifestResourceStream(item.Key)
                    ?? throw new Exception("second resource absent");
                if (!first.CanRead || !first.CanSeek || first.CanWrite || second.Position != 0)
                    throw new Exception("resource stream semantics differ");
                first.ReadByte();
                if (second.Position != 0) throw new Exception("resource positions shared");
                first.Dispose();
                using var copy = new MemoryStream();
                second.CopyTo(copy);
                if (!copy.ToArray().SequenceEqual(Convert.FromBase64String(item.Value)))
                    throw new Exception("resource bytes differ");
                try { first.ReadByte(); throw new Exception("disposed stream readable"); }
                catch (ObjectDisposedException) {}
            }
        }
    }
}
'''.replace("EXPECTED", expected).encode()
    (project / "src/ResourceControls.cs").write_bytes(helper)
    return {"schemaVersion": "lsf.dotnet.resource-fixture.v1", "count": len(rows),
            "iterations": 8, "resources": {name: {"digest": digest(payload), "size": len(payload)}
                for name, payload in payloads.items()}, "helperDigest": digest(helper),
            "runtimeExecution": "pending-signed-component"}
