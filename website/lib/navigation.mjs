function sections(items, groups, remainder) {
  const used = new Set();
  const result = [];
  for (const {label, ids = [], match = () => false, collapsed = true} of groups) {
    const selected = [...ids.flatMap(id => items.filter(item => item.id === id)),
      ...items.filter(item => !ids.includes(item.id) && match(item.id))]
      .filter(item => !used.has(item.id));
    for (const item of selected) used.add(item.id);
    if (selected.length) result.push({type: 'category', label, collapsed, items: selected});
  }
  const remaining = items.filter(item => !used.has(item.id));
  if (remaining.length) result.push({type: 'category', label: remainder, collapsed: true, items: remaining});
  return result;
}

export function buildSidebars(pages) {
  const sidebars = {start: [], learn: [], howTo: [], reference: [], understand: [], contribute: [], records: []};
  const start = new Set(['reference/standalone-node', 'installation']);
  const howTo = new Set(['phase-2-delivery', 'component-development/portable-tests', 'component-development/devcontainer']);
  const references = new Set(['phase-2-operator-workflows', 'phase-2-rollouts', 'phase-2-rollback',
    'phase-2-canary-promotion', 'phase-2-canary-observation', 'phase-2-audit',
    'component-development/guest-sdk', 'component-development/packaging', 'component-development/sbom', 'component-development/static-sites',
    ...['rust', 'c', 'typescript', 'go', 'java', 'dotnet'].map(language => `component-development/${language}-authoring`)]);
  const maintenance = new Set(['operations/maintained-security-monitoring', 'operations/native-release-promotion',
    'how-to/exercise-provider-failure-and-recovery']);
  for (const page of pages.filter(page => page.source.startsWith('docs/'))) {
    let group = 'understand';
    if (page.id === 'roadmap' || /^(phase-[01]-|phase-[23]-.*(?:completion|review)$|phase3-management-integration$|evidence\/|architecture\/cluster-freshness-handoff$|protocol\/phase-1-contract-hardening$)/.test(page.id)) group = 'records';
    else if (start.has(page.id) || page.id.startsWith('start/')) group = 'start';
    else if (references.has(page.id)) group = 'reference';
    else if (maintenance.has(page.id)) group = 'contribute';
    else if (howTo.has(page.id) || /^(operations|how-to)\//.test(page.id)) group = 'howTo';
    else if (page.id.startsWith('component-development/') || page.id.startsWith('learn/')) group = 'learn';
    else if (/^(reference|protocol)\//.test(page.id) || page.id === 'api-surface') group = 'reference';
    else if (page.id === 'development/engineering-records' || /^Phase [0-9]/.test(page.title)
      || /(?:evidence|acceptance|validation|gate|review|migration|cutover|feature-audit)/.test(page.id.replace(/^development\//, '')) && page.id.startsWith('development/')
      || /^testing\/(?:phase|sdk-provider-workflow)/.test(page.id)) group = 'records';
    else if (/^(contribute|development|testing)\//.test(page.id) || page.id === 'svg-style') group = 'contribute';
    sidebars[group].push({type: 'doc', id: page.id, label: page.title});
  }
  sidebars.start = sections(sidebars.start, [
    {label: 'Your first application', collapsed: false, ids: ['start/index', 'start/application-development', 'start/developer-setup', 'start/development-workspace']},
    {label: 'Install a node', ids: ['installation', 'reference/standalone-node']},
    {label: 'Build from source', ids: ['start/first-node']},
  ], 'Getting started');
  sidebars.learn = sections(sidebars.learn, [
    {label: 'Write and run capsules', collapsed: false, ids: ['component-development/creating-a-capsule',
      'learn/author-your-first-capsule', 'learn/deliver-and-recover-a-capsule', 'learn/use-capabilities']},
    {label: 'Call services', ids: ['learn/use-a-client']},
    {label: 'Build web applications', ids: ['learn/build-and-deliver-angular', 'component-development/angular-build']},
    {label: 'Contracts and execution', ids: ['learn/runtime-identities', 'learn/read-contracts-and-evidence']},
  ], 'Application concepts');
  sidebars.howTo = sections(sidebars.howTo, [
    {label: 'Application development', ids: ['how-to/developer-commands', 'component-development/portable-tests', 'component-development/devcontainer']},
    {label: 'Web delivery', ids: ['operations/static-route-sets', 'how-to/diagnose-angular-delivery']},
    {label: 'Operate a node', ids: ['how-to/operate-and-contribute', 'how-to/reconcile-a-policy-change', 'phase-2-delivery',
      'how-to/operate-capability-providers'], match: id => id.startsWith('operations/')},
  ], 'Operations tasks');
  sidebars.reference = sections(sidebars.reference, [
    {label: 'Command-line tools', ids: ['reference/operator-cli']},
    {label: 'Capsule language profiles', ids: ['rust', 'c', 'typescript', 'go', 'java', 'dotnet'].map(language => `component-development/${language}-authoring`)},
    {label: 'Client SDKs', match: id => /^reference\/.+-client$/.test(id)},
    {label: 'Capsules and publication', ids: ['component-development/guest-sdk', 'reference/developer-test-fixtures', 'component-development/packaging', 'component-development/sbom'],
      match: id => /^reference\/(?:publication|publisher|package|build-provenance|release|oci|raw-artifact)/.test(id)},
    {label: 'HTTP and web delivery', ids: ['component-development/static-sites'], match: id => /^reference\/(?:http|web)/.test(id)},
    {label: 'Rollouts and recovery', match: id => id.startsWith('phase-2-')},
  ], 'Protocols and management');
  sidebars.understand = sections(sidebars.understand, [
    {label: 'Architecture', match: id => id.startsWith('architecture/')},
    {label: 'Runtime and capabilities', match: id => id.startsWith('runtime/')},
    {label: 'Security and trust', match: id => /^(?:security|trust)(?:\/|-)/.test(id)},
  ], 'Execution and data models');
  const contributionOrder = ['contribute/index', 'development/toolchain', 'development/local-tests', 'development/deterministic-tests', 'development/ci-profiles'];
  const introductory = contributionOrder.flatMap(id => sidebars.contribute.filter(item => item.id === id));
  const remaining = sidebars.contribute.filter(item => !contributionOrder.includes(item.id));
  const documentation = remaining.filter(item => item.id.startsWith('development/website') || item.id === 'svg-style');
  const engineering = remaining.filter(item => !documentation.includes(item));
  sidebars.contribute = [...introductory,
    ...(documentation.length ? [{type: 'category', label: 'Documentation and website', collapsed: true, items: documentation}] : []),
    ...(engineering.length ? [{type: 'category', label: 'Build and testing references', collapsed: true, items: engineering}] : []),
  ];
  if (sidebars.records.some(item => item.id === 'development/engineering-records')) {
    sidebars.contribute.push({type: 'link', label: 'Engineering records', href: '/docs/development/engineering-records/'});
    sidebars.records.sort((left, right) => Number(right.id === 'development/engineering-records') - Number(left.id === 'development/engineering-records'));
  }
  return sidebars;
}
