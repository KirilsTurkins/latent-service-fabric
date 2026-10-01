import { ShapeError } from "./protocol/preflight.js";

type RecordValue = Record<string, unknown>;
function require(value: boolean): void { if (!value) throw new ShapeError(); }
function object(value: unknown): RecordValue {
  require(value !== null && typeof value === "object" && !Array.isArray(value));
  return value as RecordValue;
}
function id(value: unknown): boolean { return typeof value === "string" && value.length > 0 && Buffer.byteLength(value,"utf8") <= 512 && !/[\s\x00-\x1f\x7f]/.test(value); }
function hex(value: unknown): boolean { return typeof value === "string" && /^[0-9a-f]{64}$/.test(value); }
function digest(value: unknown, prefix: string): boolean { return typeof value === "string" && value.startsWith(prefix) && hex(value.slice(prefix.length)); }
function optional(value: unknown, valid: (v: unknown) => boolean): boolean { return value === undefined || valid(value); }
function list(value: unknown, maximum: number): unknown[] { require(Array.isArray(value) && value.length <= maximum); return value as unknown[]; }
function publication(value: unknown, tenant: string): void { const v=object(value); require(v.tenant===tenant && id(tenant) && digest(v.id,"publication:sha256:")); }

export function validateTargetRequest(value: RecordValue, tenant: string): void {
  require(id(value.service) && id(value.contract) && id(value.function) && optional(value.route,id) && optional(value.revisionId,id) && optional(value.routingKey,id));
  require(typeof value.maximumWaitMillis === "bigint" && value.maximumWaitMillis >= 0n && value.maximumWaitMillis <= 30000n);
  if (value.publication !== undefined) publication(value.publication,tenant);
}

export function validateTargetResponse(value: RecordValue, request: RecordValue, tenant: string): void {
  require(value.schemaVersion === 1 && value.tenant === tenant && value.service === request.service && value.contract === request.contract && value.function === request.function && id(value.route)
    && (request.route === undefined || value.route === request.route) && value.liveGrantsChecked === false);
  const revisions = new Set<unknown>();
  for (const item of list(value.candidates,32)) {
    const candidate = object(item);
    require(id(candidate.deploymentId) && id(candidate.revisionId) && !revisions.has(candidate.revisionId) && digest(candidate.componentDigest,"sha256:") && optional(candidate.packageDigest,v=>digest(v,"sha256:"))
      && (request.revisionId === undefined || candidate.revisionId === request.revisionId) && typeof candidate.routingWeight === "number" && candidate.routingWeight >= 0 && candidate.routingWeight <= 65535);
    revisions.add(candidate.revisionId);
    const reasons=list(candidate.reasons,16), dependencies=list(candidate.dependencies,32), bindings=list(candidate.httpBindings,32);
    for (const reference of [candidate.publication,candidate.requestedPublication]) if (reference !== undefined) publication(reference,tenant);
    if (request.publication !== undefined) { const expected=object(request.publication), actual=object(candidate.publication); require(actual.id===expected.id && actual.tenant===expected.tenant); }
    require(candidate.publicationKind === undefined || candidate.packageDigest !== undefined && ["capsule","browser-assets","ssr-package"].includes(candidate.publicationKind as string));
    for (const item of bindings) { const binding=object(item); require(id(binding.id) && binding.generation !== 0n && ["configured-current","deployment-changed"].includes(binding.state as string)); }
    for (const item of dependencies) {
      const dependency=object(item), binding=object(dependency.binding);
      require(id(dependency.capability) && id(dependency.providerProfile) && id(dependency.configurationDigest) && hex(dependency.policyIdentityDigest)
        && ["configured-current","policy-changed-or-revoked","provider-unavailable","publication-unavailable","route-changed-or-unavailable","inspection-indeterminate"].includes(dependency.state as string));
      require(id(binding.id) && id(binding.digest));
      for (const item of list(dependency.policies,32)) { const revision=object(item); require(id(revision.id) && id(revision.digest)); }
    }
    const preparation=object(candidate.preparation), imports=list(preparation.imports,64), typeImports=list(preparation.typeImports,64), exports=list(preparation.exports,128);
    require(imports.length+typeImports.length<=64);
    require(request.includePreparation ? preparation.state !== 4 : preparation.state === 4);
    for (const text of [preparation.engineVersion,preparation.targetTriple,preparation.cpuFeatureSet]) require(optional(text,id));
    require(optional(preparation.engineConfigurationDigest,v=>digest(v,"blake3:")) && optional(preparation.sealedMetadataFingerprint,hex));
    for (const imported of imports) require(id(imported));
    for (const imported of typeImports) require(id(imported));
    for (const item of exports) { const exported=object(item); require(id(exported.contract) && id(exported.function)); }
    if (preparation.diagnostic !== undefined) { const diagnostic=object(preparation.diagnostic); require(diagnostic.schemaVersion===1 && optional(diagnostic.profileDigest,hex)); }
    if (preparation.state === 1) require(preparation.profile !== undefined && preparation.engineVersion !== undefined && preparation.engineConfigurationDigest !== undefined && preparation.targetTriple !== undefined
      && preparation.cpuFeatureSet !== undefined && preparation.declaredBudget !== undefined && preparation.importCount === BigInt(imports.length+typeImports.length) && preparation.functionCount === BigInt(exports.length)
      && preparation.hostcallFuel !== undefined && preparation.maximumLiftedBytes !== undefined && preparation.maximumTypeNodes !== undefined);
    if (candidate.eligible) require(value.state===1 && candidate.exportCompatible===true && candidate.publication!==undefined && candidate.packageDigest!==undefined && candidate.publicationGeneration!==undefined
      && (candidate.routingWeight as number)>0 && reasons.length===1 && reasons[0]===1 && [1,4].includes(preparation.state as number) && dependencies.every(v=>object(v).state==="configured-current"));
  }
  require(value.selectedRevisionId===undefined || request.routingKey!==undefined && revisions.has(value.selectedRevisionId));
}
