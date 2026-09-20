import React from 'react';
import Layout from '@theme/Layout';
import Link from '@docusaurus/Link';
import {usePluginData} from '@docusaurus/useGlobalData';
import {useHistory, useLocation} from '@docusaurus/router';
import useIsBrowser from '@docusaurus/useIsBrowser';
import '../css/discovery.css';

type Guide = {id: string; title: string; topic: string; audience: string[]; languages: string[]; pages: {title: string; route: string; role: string}[]};
const topics: Record<string, string> = {'evaluate-install-contribute': 'Evaluation and setup', 'capsule-delivery-recovery': 'Capsules and delivery',
  'executable-clients': 'Client SDKs', 'capabilities-operators': 'Capabilities and operations', 'angular-browser': 'Angular and browsers', 'reference-evidence': 'Architecture and reference'};
const audiences: Record<string, string> = {'capsule-author': 'Capsule authors', 'client-developer': 'Client developers', contributor: 'Contributors',
  evaluator: 'Evaluators', operator: 'Operators', 'web-developer': 'Web developers'};

export default function Guides(): React.ReactNode {
  const {guides} = usePluginData('lsf-discovery') as {guides: Guide[]};
  const location = useLocation();
  const history = useHistory();
  const browser = useIsBrowser();
  const params = new URLSearchParams(browser ? location.search : '');
  const selected = {audience: params.get('audience') ?? '', language: params.get('language') ?? '', topic: params.get('topic') ?? ''};
  const options = {audience: [...new Set(guides.flatMap(guide => guide.audience))].sort(), language: [...new Set(guides.flatMap(guide => guide.languages))].sort(),
    topic: [...new Set(guides.map(guide => guide.topic))].sort()};
  const invalid = Object.entries(selected).some(([key, value]) => value && !options[key as keyof typeof options].includes(value));
  const matches = guides.filter(guide => (!selected.audience || guide.audience.includes(selected.audience))
    && (!selected.language || guide.languages.includes(selected.language)) && (!selected.topic || guide.topic === selected.topic));
  function update(key: string, value: string) {
    const next = new URLSearchParams(selected);
    if (value) next.set(key, value); else next.delete(key);
    history.replace({pathname: location.pathname, search: `?${next}`});
  }
  return <Layout title="Guide catalogue" description="Find existing LSF documentation by task, audience, SDK language and topic.">
    <main className="container lsf-discovery">
      <h1>Guide catalogue</h1>
      <p>Find current development documentation by task. References describe contracts; walkthroughs provide a sequence to follow. Each page states its supported version and verification scope.</p>
      <div className="lsf-discovery-filters">{(['audience', 'language', 'topic'] as const).map(key => <label key={key} htmlFor={`guide-${key}`}>
        {key === 'audience' ? 'Audience' : key === 'language' ? 'SDK language' : 'Topic'}
        <select id={`guide-${key}`} value={selected[key]} onChange={event => update(key, event.target.value)}>
          <option value="">All {key === 'language' ? 'languages' : key === 'audience' ? 'audiences' : 'topics'}</option>
          {selected[key] && !options[key].includes(selected[key]) && <option value={selected[key]}>Unavailable filter</option>}
          {options[key].map(value => <option key={value} value={value}>{key === 'audience' ? audiences[value] : key === 'topic' ? topics[value] : value}</option>)}
        </select>
      </label>)}</div>
      <p role="status">{invalid ? 'That filter is unavailable. Choose one of the listed options.' : matches.length ? `${matches.length} tasks with existing documentation.` : 'No tasks match these filters. Clear a filter to broaden the catalogue.'}</p>
      <p><Link to="/guides/">Clear filters</Link> · <Link to="/search/?version=development">Search development documentation</Link></p>
      <div className="foundation-grid">{!invalid && matches.map(guide => <section key={guide.id} data-guide={guide.id}>
        <h2>{guide.title}</h2><p>{topics[guide.topic]}{guide.languages.length ? ` · ${guide.languages.join(', ')}` : ''}</p>
        <ul>{guide.pages.map(page => <li key={page.route}><Link to={page.route}>{page.title}</Link> <small>({page.role === 'guide' ? 'walkthrough' : 'reference'})</small></li>)}</ul>
      </section>)}</div>
    </main>
  </Layout>;
}
