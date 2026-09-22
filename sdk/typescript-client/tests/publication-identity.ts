import type { PublicationIdentity, PublicationRef, InvocationReceipt } from "../src/index.js";
function check(value: unknown): asserts value { if (!value) throw new Error("publication model contract"); }
const component = "sha256:" + "a".repeat(64);
const rows: PublicationIdentity[] = Array.from({length: 4}, (_, i) => ({
  publication: {id: "publication:sha256:" + i.toString(16).padStart(64, "0"), tenant: i < 2 ? "a" : "b"},
  componentDigest: component, packageDigest: "sha256:" + (i % 2).toString(16).padStart(64, "0"),
}));
check(rows[0]!.componentDigest === rows[3]!.componentDigest);
check(rows[0]!.packageDigest === rows[2]!.packageDigest && rows[0]!.packageDigest !== rows[1]!.packageDigest);
check(new Set(rows.map(row => row.publication.id)).size === 4);
const invalid: PublicationRef = {id: "", tenant: "b"};
check(invalid.id === "" && invalid.tenant === "b");
const maximum = (1n << 64n) - 1n;
const unresolved: InvocationReceipt = {activationId: "known", revisionId: "revision", releaseDigest: component,
  routeGeneration: maximum, consumption: {cpuFuel: maximum, peakMemoryBytes: 0n, wallTimeMicros: 0n,
  childCalls: 0, outboundRequests: 0, stateReadBytes: 0n, stateWriteBytes: 0n,
  blobReadBytes: 0n, blobWriteBytes: 0n, logBytes: 0n, effectCount: 0}};
const current: InvocationReceipt = {...unresolved, publicationId: rows[1]!.publication.id};
check(unresolved.publicationId === undefined && current.publicationId === rows[1]!.publication.id);
check(current.releaseDigest === component && current.routeGeneration === maximum && current.consumption.cpuFuel === maximum);
