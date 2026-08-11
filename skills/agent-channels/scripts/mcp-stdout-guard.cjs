#!/usr/bin/env node
/**
 * Route non-JSON-RPC stdout to stderr so Baileys/pino logs don't break MCP stdio.
 * Load via: NODE_OPTIONS='--require …/mcp-stdout-guard.cjs'
 */
'use strict';

const origWrite = process.stdout.write.bind(process.stdout);

function looksLikeMcp(chunk) {
  const s = typeof chunk === 'string' ? chunk : chunk.toString('utf8');
  if (s.includes('"jsonrpc"')) return true;
  if (s.startsWith('Content-Length:')) return true;
  const t = s.trim();
  if (t.startsWith('{') && t.includes('"method"') && !t.includes('"hostname"')) return true;
  if (t.startsWith('{') && t.includes('"result"') && t.includes('"id"')) return true;
  if (t.startsWith('{') && t.includes('"error"') && t.includes('"id"')) return true;
  return false;
}

process.stdout.write = (chunk, encoding, cb) => {
  if (looksLikeMcp(chunk)) {
    return origWrite(chunk, encoding, cb);
  }
  return process.stderr.write(chunk, encoding, cb);
};

console.log = (...args) => console.error(...args);
