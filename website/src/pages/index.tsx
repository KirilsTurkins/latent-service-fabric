import React from 'react';
import Layout from '@theme/Layout';
import Link from '@docusaurus/Link';

const sections = [
  ['Start', '/docs/start/', 'Choose source evaluation, an approved rootless bundle or native installation.'],
  ['Learn', '/docs/learn/author-your-first-capsule/', 'Build a maintained guest, then follow trusted delivery and recovery.'],
  ['How-to', '/docs/phase-2-operator-workflows/', 'Find delivery, rollout and recovery procedures.'],
  ['Reference', '/docs/reference/operator-cli/', 'Consult CLI, API, configuration and protocol references.'],
  ['Understand', '/docs/architecture/overview/', 'Trace authority, resource ownership and later-phase boundaries.'],
  ['Contribute', '/docs/how-to/operate-and-contribute/', 'Diagnose a local node and choose focused contributor validation.'],
];

export default function Home(): React.ReactNode {
  return <Layout title="Development documentation" description="Current repository documentation; guide acceptance and released snapshots remain explicitly separate.">
    <main className="container foundation-home">
      <p className="lsf-eyebrow">Bounded execution. Explicit authority.</p>
      <h1>Latent Service Fabric documentation</h1>
      <p>This is the current <strong>development</strong> corpus, not a released documentation snapshot or a runtime service.</p>
      <p>Existing references remain authoritative. The finite migration still requires reviewed practical guides, released snapshots, accessibility/search and protected publication.</p>
      <div className="foundation-grid">{sections.map(([label, route, description]) =>
        <section key={label}><h2><Link to={route}>{label}</Link></h2><p>{description}</p></section>,
      )}</div>
      <p><Link to="/decisions/">Architecture decisions</Link> record constraints and status, not proof that a feature is delivered.</p>
      <p><Link to="/components/">Theme component review</Link> is a presentation fixture, not guide or runtime acceptance.</p>
    </main>
  </Layout>;
}
