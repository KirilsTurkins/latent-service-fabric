import React from 'react';
import Layout from '@theme/Layout';
import Link from '@docusaurus/Link';

const sections = [
  ['Start', '/docs/development/standalone-quickstart/', 'Evaluate the supported standalone boundary and prerequisites.'],
  ['Learn', '/docs/component-development/creating-a-capsule/', 'Read the existing capsule workflow and owning contracts.'],
  ['How-to', '/docs/phase-2-operator-workflows/', 'Find delivery, rollout and recovery procedures.'],
  ['Reference', '/docs/reference/operator-cli/', 'Consult CLI, API, configuration and protocol references.'],
  ['Understand', '/docs/architecture/overview/', 'Trace authority, resource ownership and later-phase boundaries.'],
  ['Contribute', '/docs/development/ci-profiles/', 'Choose focused checks without bypassing product validation.'],
];

export default function Home(): React.ReactNode {
  return <Layout title="Development documentation" description="Current repository documentation; guide acceptance and released snapshots remain explicitly separate.">
    <main className="container foundation-home">
      <h1>Latent Service Fabric documentation</h1>
      <p>This is the current <strong>development</strong> corpus, not a released documentation snapshot or a runtime service.</p>
      <p>Existing references remain authoritative. The finite migration still requires reviewed practical guides, released snapshots, accessibility/search and protected publication.</p>
      <div className="foundation-grid">{sections.map(([label, route, description]) =>
        <section key={label}><h2><Link to={route}>{label}</Link></h2><p>{description}</p></section>,
      )}</div>
      <p><Link to="/decisions/">Architecture decisions</Link> record constraints and status, not proof that a feature is delivered.</p>
    </main>
  </Layout>;
}
