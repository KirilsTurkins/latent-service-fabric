import React, {type ReactNode} from 'react';
import {useDocsVersion} from '@docusaurus/plugin-content-docs/client';
import useDocusaurusContext from '@docusaurus/useDocusaurusContext';
import OriginalBadge from '@theme-original/DocVersionBadge';
import type {Props} from '@theme/DocVersionBadge';

type Publication = {version: string; runtimeVersion: string; runtimeSource: string; documentationSource: string;
  exampleSource: string; snapshotIdentity: string; profile: string; verification: string};
export default function DocVersionBadge(props: Props): ReactNode {
  const version = useDocsVersion();
  const {siteConfig} = useDocusaurusContext();
  const publications = siteConfig.customFields?.publications as Publication[];
  const publication = publications.find(item => item.version === version.version);
  const current = siteConfig.customFields?.contentIdentity as {revision: string};
  if (version.version !== 'current' && !publication) throw new Error('Missing document publication identity');
  return <>
    <OriginalBadge {...props} />
    <aside className="alert alert--secondary margin-bottom--md" aria-label="Documentation support" data-doc-version={publication?.version ?? 'development'}>
      <strong>{publication ? `${publication.runtimeVersion} · ${publication.profile}` : 'Development · Phase 3 work in progress'}</strong>
      <p>{publication ? publication.verification : 'Implemented features and unfinished work are documented together. Page-specific receipts define verification; this channel is not a released support promise.'}</p>
      <a href={`https://github.com/KirilsTurkins/latent-service-fabric/tree/${publication?.documentationSource ?? current.revision}`}>Exact documentation source</a>
      {publication && <details><summary>Publication identity</summary>
        <p>Runtime source: <code>{publication.runtimeSource}</code></p>
        <p>Example source: <code>{publication.exampleSource}</code></p>
        <p>Snapshot: <code>{publication.snapshotIdentity}</code></p>
      </details>}
    </aside>
  </>;
}
