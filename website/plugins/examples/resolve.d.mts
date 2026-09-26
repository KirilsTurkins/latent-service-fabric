export type ExampleLanguage = 'rust' | 'typescript' | 'go' | 'c' | 'java' | 'csharp';
export type ExampleTarget = 'client' | 'browser' | 'guest';
export type ExampleVerification =
  | {level: 'source-extracted'; reason: 'working-copy' | 'no-evidence' | 'evidence-unavailable'
      | 'evidence-digest-mismatch' | 'invalid-evidence' | 'evidence-not-passed'
      | 'evidence-source-mismatch' | 'evidence-scope-mismatch'}
  | {level: 'compile-unit' | 'real-node'; basis: 'reviewed-record'; execution: 'compile-unit' | 'test-double' | 'real-node';
      sourceRevision: string; evidenceSha256: string; toolchain: string; run: string; scope: string};
export interface ExampleVariant {
  language: ExampleLanguage;
  kind: 'maintained' | 'synthetic' | 'test-double';
  environment: 'node' | 'native' | 'browser' | 'component';
  source: {path: string; revision: string; sha256: string; matchesRevision: boolean; url: string | null};
  validation: {target: string | null; instructions: string | null};
  verification: ExampleVerification;
  snippet: {code: string; startLine: number; endLine: number; sha256: string};
}
export interface ExampleBundle {
  schema: 1;
  documentVersion: string;
  documentationRevision: string;
  sourceRevision: string;
  inputDigest: string;
  examples: Array<{id: string; title: string; audience: string; target: ExampleTarget;
    regions: Array<{id: string; variants: ExampleVariant[]}>}>;
}
export interface ExampleRequest {documentVersion: string; example: string; region: string}
export function resolveExample(bundle: ExampleBundle, request: ExampleRequest): {
  id: string; title: string; audience: string; target: ExampleTarget; region: string; variants: ExampleVariant[];
};
