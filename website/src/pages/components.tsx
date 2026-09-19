import React, {useState} from 'react';
import Layout from '@theme/Layout';
import CodeBlock from '@theme/CodeBlock';
import Admonition from '@theme/Admonition';
import Tabs from '@theme/Tabs';
import TabItem from '@theme/TabItem';
import Link from '@docusaurus/Link';

const sample = 'export function describe(name: string): string {\n  const limit = 12;\n  return `${name.slice(0, limit)}: example only`;\n}';
const syntax = ['text', 'comment', 'keyword', 'string', 'number', 'function', 'variable'];

export default function Components(): React.ReactNode {
  const [count, setCount] = useState(0);
  return <Layout title="Theme component review" description="A bounded UI review fixture, not an SDK example or a product acceptance result.">
    <main className="container lsf-gallery">
      <p className="lsf-eyebrow">Design review fixture</p>
      <h1>Readable by design</h1>
      <p>Review the same components in light, dark and system modes. These specimens make no runtime or guide-completion claim.</p>
      <p><Link to="/docs/svg-style/">Palette and illustration contract</Link> · <Link to="/docs/development/website/">Website checks</Link></p>
      <section aria-labelledby="reading">
        <h2 id="reading">Reading and navigation</h2>
        <p>Body text stays quiet; <a href="#controls">links remain visibly underlined</a>, not identifiable by color alone. <strong>Authority is explicit.</strong> <em>Uncertainty stays visible.</em></p>
        <p className="lsf-muted">Secondary text still meets normal-text contrast. Selected text, keyboard focus and hover each have their own checked pairing.</p>
        <blockquote>A successful render is evidence of presentation only, not proof that a procedure works.</blockquote>
        <details><summary>Keyboard-operable disclosure</summary><p>Enter or Space opens this native disclosure. Escape is reserved for overlays, not invented navigation behavior.</p></details>
      </section>
      <section aria-labelledby="code">
        <h2 id="code">Code and syntax</h2>
        <CodeBlock language="typescript" title="UI fixture — not a supported SDK example" showLineNumbers>{sample}</CodeBlock>
        <div className="lsf-syntax" aria-label="All syntax color roles">{syntax.map(token => <code key={token} data-syntax={token} style={{color: `var(--lsf-code-${token})`}}>{token}</code>)}</div>
        <p>Inline <code>example-only</code> identifiers remain distinct from commands to execute.</p>
      </section>
      <section aria-labelledby="tabs">
        <h2 id="tabs">Standard tabs</h2>
        <Tabs aria-label="Review specimen" defaultValue="contract">
          <TabItem value="contract" label="Contract"><p>The selected tab has a filled surface and underline, as well as its tab semantics.</p></TabItem>
          <TabItem value="evidence" label="Evidence"><p>Arrow keys switch the standard Docusaurus tabs. This is not the future per-language control.</p></TabItem>
        </Tabs>
      </section>
      <section aria-labelledby="callouts">
        <h2 id="callouts">Labelled callouts</h2>
        <Admonition type="note" title="Note: specimen only">The default callout has a label and an icon.</Admonition>
        <Admonition type="tip" title="Success: fixture passed">This states a UI fixture result, not an authorization or product delivery result.</Admonition>
        <Admonition type="info" title="Information: review scope">Read the <a href="#reading">reading specimen</a> in both themes.</Admonition>
        <Admonition type="warning" title="Warning: review pending">Human review remains necessary. Color alone does not encode this status.</Admonition>
        <Admonition type="danger" title="Failure: specimen denied">This demonstrates a denied state with a label and an icon.</Admonition>
      </section>
      <section aria-labelledby="table">
        <h2 id="table">Tables</h2>
        <div className="lsf-table-region" role="region" aria-label="Presentation evidence table" tabIndex={0}>
          <table><caption>Presentation fixture states, not product acceptance</caption><thead><tr><th scope="col">Specimen</th><th scope="col">State</th><th scope="col">Boundary</th></tr></thead><tbody>
            <tr><th scope="row">Token pair</th><td><span className="lsf-status">✓ Checked</span></td><td>Only the named foreground/background pair</td></tr>
            <tr><th scope="row">Procedure</th><td><span className="lsf-status">△ Pending review</span></td><td>Rendering cannot establish successful execution</td></tr>
            <tr><th scope="row">Deployment</th><td><span className="lsf-status">× Not claimed</span></td><td>This is a local production-build fixture</td></tr>
          </tbody></table>
        </div>
      </section>
      <section aria-labelledby="controls">
        <h2 id="controls">Controls</h2>
        <div className="lsf-controls">
          <button type="button" className="button button--primary" onClick={() => setCount(value => value + 1)}>Exercise control</button>
          <button type="button" className="button" disabled>Unavailable (disabled)</button>
          <label>Review label<input defaultValue="Example only" maxLength={40}/></label>
          <label>Review option<select defaultValue="one"><option value="one">First specimen</option><option value="two">Second specimen</option></select></label>
          <label><input type="checkbox"/> Mark this local specimen</label>
        </div>
        <p role="status" aria-live="polite">Control exercised {count} times.</p>
      </section>
    </main>
  </Layout>;
}
