import React, {useEffect, useMemo, useState} from 'react';
import Layout from '@theme/Layout';
import Link from '@docusaurus/Link';
import {useHistory, useLocation} from '@docusaurus/router';
import useIsBrowser from '@docusaurus/useIsBrowser';
import useDocusaurusContext from '@docusaurus/useDocusaurusContext';
import MiniSearch from 'minisearch';
import {SEARCH_LIMITS, searchDocuments, searchOptions, searchState} from '../../lib/search.mjs';
import '../css/discovery.css';

export default function Search(): React.ReactNode {
  const {siteConfig} = useDocusaurusContext();
  const location = useLocation();
  const history = useHistory();
  const browser = useIsBrowser();
  const publications = siteConfig.customFields?.publications as {version: string; runtimeVersion: string; profile: string}[];
  const channels = ['development', ...publications.map(item => item.version)];
  const selected = searchState(browser ? location.search : '', channels);
  const [draft, setDraft] = useState('');
  const [index, setIndex] = useState<MiniSearch | null>(null);
  const [failure, setFailure] = useState('');
  useEffect(() => { setDraft(selected.query); }, [selected.query]);
  useEffect(() => {
    const cancellation = new AbortController();
    async function load() {
      try {
        const response = await fetch(`${siteConfig.baseUrl}search-index.json`, {signal: cancellation.signal, credentials: 'omit'});
        if (!response.ok || !response.body) throw new Error('index unavailable');
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let bytes = 0;
        let json = '';
        try {
          while (true) {
            const chunk = await reader.read();
            if (chunk.done) break;
            bytes += chunk.value.length;
            if (bytes > SEARCH_LIMITS.bytes) throw new Error('index size');
            json += decoder.decode(chunk.value, {stream: true});
          }
        } finally { await reader.cancel(); }
        json += decoder.decode();
        const value = JSON.parse(json);
        const identity = siteConfig.customFields?.contentIdentity as {revision: string};
        if (value.schema !== 1 || value.sourceRevision !== identity.revision || value.baseUrl !== siteConfig.baseUrl || value.records > SEARCH_LIMITS.records
          || JSON.stringify(value.channels) !== JSON.stringify(channels)) throw new Error('index identity');
        if (!cancellation.signal.aborted) setIndex(MiniSearch.loadJSON(value.index, searchOptions));
      } catch {
        if (!cancellation.signal.aborted) setFailure('Search is unavailable. Reload this page or use the guide catalogue.');
      }
    }
    void load();
    return () => cancellation.abort();
  }, [siteConfig.baseUrl, publications]);
  const results = useMemo(() => index && !selected.error ? searchDocuments(index, selected.query, selected.version) : [],
    [index, selected.query, selected.version, selected.error]);
  function update(query: string, version: string) {
    history.replace({pathname: location.pathname, search: `?${new URLSearchParams({q: query, version})}`});
    try { if (channels.includes(version)) localStorage.setItem('lsf-documentation-channel', version); } catch { /* Optional preference. */ }
  }
  return <Layout title="Search documentation" description="Search public LSF guides locally within your selected documentation version.">
    <main className="container lsf-discovery">
      <h1>Search documentation</h1>
      <p>Search guides, reference pages, section headings and available code examples in one documentation version. Queries stay in your browser.</p>
      <form className="lsf-discovery-filters" onSubmit={event => { event.preventDefault(); update(draft, selected.version); }} role="search">
        <label htmlFor="documentation-query">Search terms
          <input id="documentation-query" type="search" value={draft} maxLength={SEARCH_LIMITS.query} onChange={event => setDraft(event.target.value)} autoComplete="off" />
        </label>
        <label htmlFor="documentation-version">Documentation version
          <select id="documentation-version" value={selected.version} onChange={event => update(draft, event.target.value)}>
            {!channels.includes(selected.version) && <option value={selected.version}>Unavailable version</option>}
            <option value="development">Development — work in progress</option>
            {publications.map(item => <option key={item.version} value={item.version}>{item.runtimeVersion} · {item.profile}</option>)}
          </select>
        </label>
        <button className="button button--primary" type="submit">Search</button>
      </form>
      <p role="status" aria-live="polite">{selected.error ?? (failure || (!index ? 'Loading the local search index…'
        : !selected.query.trim() ? 'Enter a term to search this documentation version.'
          : results.length ? `${results.length} result${results.length === 1 ? '' : 's'} in ${selected.version}.`
            : `No results in ${selected.version}. Try fewer terms or choose another version explicitly.`))}</p>
      <ol className="lsf-search-results">{results.map(result => <li key={result.id} data-search-version={result.version}>
        <h2><Link to={result.route}>{result.title}{result.heading !== result.title ? `: ${result.heading}` : ''}</Link></h2>
        <p className="lsf-search-scope"><strong>{result.version}</strong> · {result.profile}</p>
        <p>{result.excerpt}</p>
      </li>)}</ol>
      <p><Link to="/guides/">Browse the guide catalogue</Link> or choose Start, Learn, How-to, Reference, Understand or Contribute above.</p>
      <noscript>Local search requires JavaScript. All guide pages and the catalogue remain readable without it.</noscript>
    </main>
  </Layout>;
}
