export function buildSidebars(pages) {
  const sidebars = {start: [], learn: [], howTo: [], reference: [], understand: [], contribute: [], records: []};
  const start = new Set(['reference/standalone-node']);
  const howTo = new Set(['phase-2-delivery']);
  const references = new Set(['phase-2-operator-workflows', 'phase-2-rollouts', 'phase-2-rollback',
    'phase-2-canary-promotion', 'phase-2-canary-observation', 'phase-2-audit',
    'component-development/guest-sdk', 'component-development/packaging', 'component-development/sbom', 'component-development/static-sites']);
  const maintenance = new Set(['operations/maintained-security-monitoring', 'operations/native-release-promotion']);
  for (const page of pages.filter(page => page.source.startsWith('docs/'))) {
    let group = 'understand';
    if (page.id === 'roadmap' || /^(phase-[01]-|phase-[23]-.*(?:completion|review)$|phase3-management-integration$|evidence\/|architecture\/cluster-freshness-handoff$|protocol\/phase-1-contract-hardening$)/.test(page.id)) group = 'records';
    else if (start.has(page.id) || page.id.startsWith('start/')) group = 'start';
    else if (references.has(page.id)) group = 'reference';
    else if (maintenance.has(page.id)) group = 'contribute';
    else if (page.id.startsWith('component-development/') || page.id.startsWith('learn/')) group = 'learn';
    else if (howTo.has(page.id) || /^(operations|how-to)\//.test(page.id)) group = 'howTo';
    else if (/^(reference|protocol)\//.test(page.id) || page.id === 'api-surface') group = 'reference';
    else if (page.id === 'development/engineering-records' || /^Phase [0-9]/.test(page.title)
      || /(?:evidence|acceptance|validation|gate|review|migration|cutover|feature-audit)/.test(page.id.replace(/^development\//, '')) && page.id.startsWith('development/')
      || /^testing\/(?:phase|sdk-provider-workflow)/.test(page.id)) group = 'records';
    else if (/^(contribute|development|testing)\//.test(page.id) || page.id === 'svg-style') group = 'contribute';
    sidebars[group].push({type: 'doc', id: page.id, label: page.title});
  }
  const operatorOrder = ['how-to/operate-and-contribute', 'how-to/reconcile-a-policy-change', 'phase-2-delivery'];
  sidebars.howTo = [...operatorOrder.flatMap(id => sidebars.howTo.filter(item => item.id === id)),
    ...sidebars.howTo.filter(item => !operatorOrder.includes(item.id))];
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
