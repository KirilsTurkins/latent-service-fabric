'use strict';

// This local derivation fixes GHSA-vfj7-8cjw-p6xm in upstream braces 3.0.3.
// The limit is fixed: options cannot disable the recursive-walker boundary.
const MAX_DEPTH = 128;
const {MAX_LENGTH} = require('./constants');
const MAX_NODES = 2 * MAX_LENGTH + 3;

const nesting = depth => {
  if (depth > MAX_DEPTH) {
    throw new SyntaxError('Brace AST nesting exceeds the fixed depth limit (128)');
  }
};

// Check child edges iteratively before any upstream recursive AST walker runs.
// parent/prev are ordinary parser backreferences, not child edges.
const ast = root => {
  // Parsed subtrees and imbalanced input can retain parents outside the child
  // traversal. Accept those ordinary links, while refusing parent cycles.
  const parentDepth = new Map();
  const parents = node => {
    const path = [];
    const seen = new Set();
    let parent = node.parent;
    while (parent && !parentDepth.has(parent)) {
      if (parentDepth.size + path.length >= MAX_NODES) {
        throw new SyntaxError('Brace AST exceeds the fixed node limit');
      }
      if (seen.has(parent) || path.length >= MAX_DEPTH + 1) {
        throw new SyntaxError('Invalid brace AST parent edge');
      }
      seen.add(parent);
      path.push(parent);
      parent = parent.parent;
    }
    let depth = parent ? parentDepth.get(parent) : 0;
    if (depth + path.length > MAX_DEPTH + 1) {
      throw new SyntaxError('Invalid brace AST parent edge');
    }
    for (let i = path.length - 1; i >= 0; i--) {
      parentDepth.set(path[i], ++depth);
    }
  };
  const active = new Set();
  const stack = [{node: root, depth: 0, index: 0, entered: false}];
  let visits = 0;
  while (stack.length) {
    const frame = stack[stack.length - 1];
    const node = frame.node;
    if (!frame.entered) {
      if (++visits > MAX_NODES) {
        throw new SyntaxError('Brace AST exceeds the fixed node limit');
      }
      nesting(frame.depth);
      if (node === null || typeof node !== 'object') {
        throw new TypeError('Expected an AST node');
      }
      if (active.has(node)) {
        throw new SyntaxError('Cyclic brace AST child edges');
      }
      if (node.nodes !== undefined && !Array.isArray(node.nodes)) {
        throw new TypeError('Expected AST child nodes to be an array');
      }
      parents(node);
      active.add(node);
      frame.entered = true;
    }
    const children = node.nodes || [];
    if (frame.index < children.length) {
      const child = children[frame.index++];
      stack.push({node: child, depth: frame.depth + (child && child.nodes ? 1 : 0), index: 0, entered: false});
    } else {
      active.delete(node);
      stack.pop();
    }
  }
};

module.exports = {nesting, ast};
