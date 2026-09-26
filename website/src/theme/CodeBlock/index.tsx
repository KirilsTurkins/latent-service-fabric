import React from 'react';
import CodeBlock from '@theme-original/CodeBlock';
import type {Props} from '@theme/CodeBlock';

export default function DownloadableCodeBlock(props: Props) {
  const filename = /(?:^|\s)download=([a-z0-9-]+\.(?:ps1|sh|py))(?:\s|$)/.exec(props.metastring ?? '')?.[1];
  if (!filename || typeof props.children !== 'string') return <CodeBlock {...props} />;
  const script = props.children;
  function download() {
    const url = URL.createObjectURL(new Blob([script], {type: 'text/plain;charset=utf-8'}));
    const link = document.createElement('a');
    link.href = url;
    link.download = filename!;
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return <div className="lsf-setup-script" data-setup-script={filename}>
    <p><button type="button" className="button button--primary" onClick={download}>Download {filename}</button></p>
    <details><summary>View the setup script</summary><CodeBlock {...props} /></details>
    <noscript>Expand the script and save it as {filename}, or enable JavaScript to download it.</noscript>
  </div>;
}
