export function buildSidebars(pages) {
  const sidebars = {start: [], learn: [], howTo: [], reference: [], understand: [], contribute: []};
  const start = new Set(['development/standalone-quickstart', 'reference/standalone-node', 'roadmap']);
  const howTo = new Set(['phase-2-delivery', 'phase-2-operator-workflows', 'phase-2-rollouts', 'phase-2-rollback', 'phase-2-canary-promotion', 'phase-2-canary-observation']);
  for (const page of pages.filter(page => page.source.startsWith('docs/'))) {
    let group = 'understand';
    if (start.has(page.id)) group = 'start';
    else if (page.id.startsWith('component-development/') || page.id.startsWith('learn/')) group = 'learn';
    else if (howTo.has(page.id) || /^(operations|how-to)\//.test(page.id)) group = 'howTo';
    else if (/^(reference|protocol)\//.test(page.id) || page.id === 'api-surface') group = 'reference';
    else if (/^(development|testing)\//.test(page.id) || page.id === 'svg-style') group = 'contribute';
    sidebars[group].push({type: 'doc', id: page.id, label: page.title});
  }
  return sidebars;
}
