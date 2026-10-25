/** Selected lsf-node-buffer-global-v1 only. This is the finite owned module,
 * not a Node process or an assertion of complete Node Buffer compatibility. */
export {};
declare global {
  var Buffer: typeof import('node:buffer').Buffer;
  type Buffer = import('node:buffer').Buffer;
}
