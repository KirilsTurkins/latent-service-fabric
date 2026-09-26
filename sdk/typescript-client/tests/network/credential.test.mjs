import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync, chmodSync, symlinkSync, linkSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { protectedFile } from "../../examples/protected-file.mjs";

test("example credential input rejects unsupported protection profiles", () => {
  assert.throws(() => protectedFile("relative-token", 256));
  assert.throws(() => protectedFile("/tmp/../token", 256));
});

test("Linux example reads private owned descriptors and rejects unsafe credential aliases", { skip: process.platform !== "linux" || process.arch !== "x64" }, () => {
  const root = mkdtempSync(join(tmpdir(), "lsf-node-credential-"));
  const path = join(root, "token");
  try {
    chmodSync(root, 0o700);
    writeFileSync(path, "LSF-PUBLIC-CREDENTIAL-FILE-TEST-ONLY", { mode: 0o600 });
    assert.equal(protectedFile(path, 256).toString(), "LSF-PUBLIC-CREDENTIAL-FILE-TEST-ONLY");
    assert.throws(() => protectedFile(path, 16));
    chmodSync(path, 0o644); assert.throws(() => protectedFile(path, 256)); chmodSync(path, 0o600);
    symlinkSync(path, join(root, "alias")); assert.throws(() => protectedFile(join(root, "alias"), 256));
    linkSync(path, join(root, "hardlink")); assert.throws(() => protectedFile(path, 256));
  } finally { rmSync(root, { recursive: true, force: true }); }
});
