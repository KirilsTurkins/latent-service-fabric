import { constants, openSync, closeSync, fstatSync, readSync } from "node:fs";

export function protectedFile(path, maximum) {
  if (process.platform !== "linux" || process.arch !== "x64" || typeof process.geteuid !== "function"
    || typeof path !== "string" || path.length > 4096 || !path.startsWith("/")
    || !Number.isSafeInteger(maximum) || maximum < 1 || maximum > 16384) throw new Error("protected-file-profile");
  const parts = path.slice(1).split("/");
  if (parts.length > 64 || parts.some((part) => !part || part === "." || part === ".." || part.length > 255)) throw new Error("protected-file-path");
  const flags = constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK;
  const owner = BigInt(process.geteuid());
  let directory;
  let file;
  let buffer;
  try {
    directory = openSync("/", flags | constants.O_DIRECTORY);
    for (const part of parts.slice(0, -1)) {
      const before = fstatSync(directory, { bigint: true });
      const sticky = before.uid === 0n && (before.mode & 0o1002n) === 0o1002n;
      if (!before.isDirectory() || before.uid !== 0n && before.uid !== owner
        || ((before.mode & 0o022n) !== 0n && !sticky)) throw new Error("protected-file-parent");
      const next = openSync(`/proc/self/fd/${directory}/${part}`, flags | constants.O_DIRECTORY);
      closeSync(directory);
      directory = next;
    }
    const parent = fstatSync(directory, { bigint: true });
    if (!parent.isDirectory() || parent.uid !== owner || (parent.mode & 0o077n) !== 0n) throw new Error("protected-file-private-directory");
    file = openSync(`/proc/self/fd/${directory}/${parts.at(-1)}`, flags);
    const before = fstatSync(file, { bigint: true });
    if (!before.isFile() || before.uid !== owner || before.nlink !== 1n || (before.mode & 0o7777n) !== 0o600n
      || before.size === 0n || before.size > BigInt(maximum)) throw new Error("protected-file-metadata");
    buffer = Buffer.alloc(maximum + 1);
    let count = 0;
    while (count < buffer.length) {
      const received = readSync(file, buffer, count, buffer.length - count, null);
      if (received === 0) break;
      count += received;
    }
    const after = fstatSync(file, { bigint: true });
    if (count > maximum || BigInt(count) !== before.size || ["dev", "ino", "mode", "nlink", "uid", "gid", "size", "mtimeNs", "ctimeNs"].some((key) => before[key] !== after[key])) throw new Error("protected-file-changed");
    return Buffer.from(buffer.subarray(0, count));
  } catch {
    throw new Error("protected-file-rejected");
  } finally {
    buffer?.fill(0);
    if (file !== undefined) closeSync(file);
    if (directory !== undefined) closeSync(directory);
  }
}
