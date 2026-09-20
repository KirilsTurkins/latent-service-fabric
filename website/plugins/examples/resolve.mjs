// Browser-safe boundary shared by static rendering, CodeExample (#352), and
// publication snapshots (#353). A missing version/region never uses development.
export function resolveExample(bundle, {documentVersion, example, region}) {
  if (!bundle || bundle.schema !== 1 || bundle.documentVersion !== documentVersion
    || !/^[a-f0-9]{40}$/.test(bundle.documentationRevision)
    || !/^[a-f0-9]{40}$/.test(bundle.sourceRevision)) throw new Error('Example document-version identity mismatch');
  const scenario = bundle.examples.find(entry => entry.id === example);
  if (!scenario) throw new Error('Example is unavailable in this document version');
  const selected = scenario.regions.find(entry => entry.id === region);
  if (!selected?.variants.length) throw new Error('Example region is unavailable in this document version');
  return {id: scenario.id, title: scenario.title, audience: scenario.audience,
    target: scenario.target, region: selected.id, variants: selected.variants};
}
