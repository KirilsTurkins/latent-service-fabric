import React, {useEffect, useId, useRef, useState, type ReactNode} from 'react';
import Tabs from '@theme/Tabs';
import TabItem from '@theme/TabItem';
import CodeBlock from '@theme/CodeBlock';
import {usePluginData} from '@docusaurus/useGlobalData';
import {useLocation} from '@docusaurus/router';
import useIsBrowser from '@docusaurus/useIsBrowser';
import {useStorageSlot} from '@docusaurus/theme-common';
import {resolveExample, type ExampleBundle, type ExampleLanguage, type ExampleVariant} from '../../../plugins/examples/resolve.mjs';
import './styles.css';

const labels: Record<ExampleLanguage, string> = {rust: 'Rust', typescript: 'TypeScript', go: 'Go', c: 'C', java: 'Java', csharp: 'C#/.NET'};
type Props = {example: string; region: string; documentVersion: string};

function Verification({variant}: {variant: ExampleVariant}): ReactNode {
  const proof = variant.verification;
  return <>
    <p className="lsf-example-verification">{proof.level === 'source-extracted'
      ? 'Source extraction only; compilation and real-node execution are unverified.'
      : proof.level === 'real-node'
        ? 'Real-node validation from a matching reviewed record.'
        : 'Compilation or local tests from a matching reviewed record; not real-node proof.'}</p>
    <details><summary>Source and validation details</summary>
      <p>Source revision: <code>{variant.source.revision}</code></p>
      <p>Source SHA-256: <code>{variant.source.sha256}</code></p>
      <p>Snippet SHA-256: <code>{variant.snippet.sha256}</code></p>
      {variant.validation.target && <p><a href={variant.validation.target}>Validation target</a> (not executed by this website).</p>}
      {variant.validation.instructions && <p><a href={variant.validation.instructions}>Owner instructions</a></p>}
      {proof.level === 'source-extracted' ? <p>Evidence state: <code>{proof.reason}</code>.</p>
        : <p>Execution: {proof.execution}. Toolchain: {proof.toolchain}. Run: {proof.run}. Scope: {proof.scope}.</p>}
    </details>
  </>;
}

function Panel({variant, group, query, identifier, tabIdentifier, version}: {
  variant: ExampleVariant; group: string; query: string; identifier: string; tabIdentifier: string; version: string;
}): ReactNode {
  const ref = useRef<HTMLDivElement>(null);
  const [copyStatus, setCopyStatus] = useState('');
  const [stored] = useStorageSlot(`docusaurus.tab.${group}`);
  const location = useLocation();
  const isBrowser = useIsBrowser();
  const requested = isBrowser ? new URLSearchParams(location.search).get(query) ?? stored : null;
  const language = labels[variant.language];
  // TabItem owns visibility and keyboard semantics. Its pinned API does not
  // forward panel attributes, so the narrow wrapper binds the rendered panel.
  useEffect(() => {
    const panel = ref.current?.closest('[role="tabpanel"]');
    if (panel) {
      panel.id = identifier;
      panel.setAttribute('aria-labelledby', tabIdentifier);
    }
  }, [identifier, tabIdentifier]);
  async function copy() {
    try {
      await navigator.clipboard.writeText(variant.snippet.code);
      setCopyStatus(`${language} snippet copied.`);
    } catch {
      setCopyStatus('Clipboard unavailable. Select and copy the code below.');
    }
  }
  return <div ref={ref} data-example-language={variant.language}>
    {requested && requested !== variant.language && <p className="lsf-example-selection" role="status">
      The requested language is unavailable for this example in {version}. Showing {language} ({variant.environment}).
    </p>}
    <p><strong>{language}</strong> · {variant.environment} · {variant.kind === 'synthetic' ? 'Synthetic UI fixture; not an SDK implementation' : variant.kind}</p>
    <button className="button button--secondary button--sm" type="button" onClick={copy}>Copy {language} snippet</button>
    <span className="lsf-example-copy-status" role="status">{copyStatus}</span>
    <div className="lsf-example-code"><CodeBlock language={variant.language}>{variant.snippet.code}</CodeBlock></div>
    <p>{variant.source.url ? <a href={variant.source.url}>Complete {language} source at {variant.source.revision.slice(0, 12)}</a>
      : 'Working-copy source; no commit-bound source link is available.'}</p>
    <Verification variant={variant} />
  </div>;
}

export function ExampleView({bundle, ...request}: Props & {bundle: ExampleBundle}): ReactNode {
  const identifier = useId();
  const example = resolveExample(bundle, request);
  const group = `lsf-example-${example.target}`;
  const query = `lsf-${example.target}-language`;
  return <section className="lsf-code-example" aria-label={example.title} data-example={example.id} data-document-version={request.documentVersion}>
    <p><strong>{example.title}</strong> · {example.target} · {request.documentVersion}</p>
    <Tabs groupId={group} queryString={query} defaultValue={example.variants[0].language} lazy={false}
      values={example.variants.map(variant => ({value: variant.language, label: labels[variant.language],
        attributes: {id: `${identifier}-${variant.language}-tab`, 'aria-controls': `${identifier}-${variant.language}-panel`}}))}>
      {example.variants.map(variant => <TabItem key={variant.language} value={variant.language} label={labels[variant.language]}>
        <Panel variant={variant} group={group} query={query} version={request.documentVersion}
          identifier={`${identifier}-${variant.language}-panel`} tabIdentifier={`${identifier}-${variant.language}-tab`} />
      </TabItem>)}
    </Tabs>
  </section>;
}

export default function CodeExample(props: Props): ReactNode {
  const bundle = usePluginData('lsf-examples') as ExampleBundle;
  return <ExampleView bundle={bundle} {...props} />;
}
