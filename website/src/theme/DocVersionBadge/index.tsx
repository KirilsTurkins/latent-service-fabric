import React, {type ReactNode} from 'react';
import {useDocsVersion} from '@docusaurus/plugin-content-docs/client';
import useDocusaurusContext from '@docusaurus/useDocusaurusContext';
import {useLocation} from '@docusaurus/router';
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
  const learningPage = /\/docs\/(?:[^/]+\/)?(?:(?:start|learn|component-development|how-to|operations)\/|installation\/|phase-2-(?:delivery|audit|canary-observation|canary-promotion|operator-workflows|rollback|rollouts)\/)/.test(useLocation().pathname);
  if (version.version !== 'current' && !publication) throw new Error('Missing document publication identity');
  return <>
    <OriginalBadge {...props} />
    <aside className="alert alert--secondary margin-bottom--md" aria-label="Documentation support" data-doc-version={publication?.version ?? 'development'}>
      <strong>{publication ? learningPage ? `Version ${publication.runtimeVersion}` : `${publication.runtimeVersion} · ${publication.profile}` : 'Development preview'}</strong>
      <p>{publication ? learningPage ? 'These instructions are for this version. Select Development for the latest guides.' : publication.verification : 'These guides describe current development. Start with “Build your first application” for the packaged tools, or select a released version from the menu.'}</p>
      {!learningPage && <a href={`https://github.com/KirilsTurkins/latent-service-fabric/tree/${publication?.documentationSource ?? current.revision}`}>Exact documentation source</a>}
      {publication && !learningPage && <details><summary>Publication identity</summary>
        <p>Runtime source: <code>{publication.runtimeSource}</code></p>
        <p>Example source: <code>{publication.exampleSource}</code></p>
        <p>Snapshot: <code>{publication.snapshotIdentity}</code></p>
      </details>}
    </aside>
  </>;
}
