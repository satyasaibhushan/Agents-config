// The local catalog stays available when the authenticated remote is unavailable.
import { spawnSync } from 'node:child_process';
import { createHash, randomUUID } from 'node:crypto';
import { constants } from 'node:fs';
import { mkdir, lstat, readdir, open, unlink, link } from 'node:fs/promises';
import { homedir } from 'node:os';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js';
import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { CallToolRequestSchema, ListToolsRequestSchema, ErrorCode, McpError } from '@modelcontextprotocol/sdk/types.js';

const endpoint = 'https://hindsight.bhushan.fun/api/mcp';
const string = maxLength => ({ type: 'string', minLength: 1, maxLength });
// Mirrors HindSight's ingestion contract. Remote validation remains authoritative.
export const feedbackTool = {
  name: 'submit_feedback',
  description: 'Record concrete, attributable feedback on shared instructions, skills, code or tools. Never include secrets or transcripts. Failed delivery is retained privately for manual replay with the same request_id.',
  inputSchema: {
    type: 'object', additionalProperties: false,
    required: ['request_id', 'friction', 'improvement', 'category'],
    properties: {
      request_id: { type: 'string', pattern: '^[A-Za-z0-9._:-]{8,128}$', description: 'Client-generated idempotency key; reuse only for the identical submission' },
      friction: string(4000), improvement: string(4000),
      category: { type: 'string', description: 'instructions/skills: editable shared instructions or skills; codebase; collaboration: working practices; connector/tooling: tools and connectors', enum: ['instructions', 'skills', 'codebase', 'collaboration', 'connector', 'tooling', 'environment', 'documentation', 'workflow', 'performance', 'other'] },
      task: string(300), source: string(300), repository: string(300),
      outcome: { type: 'string', enum: ['completed', 'recovered', 'workaround', 'failed', 'blocked', 'unresolved'] },
      confidence: { type: 'string', enum: ['low', 'medium', 'high'] },
    },
  },
};
const localError = code => Object.assign(new Error(code), { localCategory: code });
function validated(input) {
  if (!input || typeof input !== 'object' || Array.isArray(input)) throw localError('invalid-input');
  for (const key of feedbackTool.inputSchema.required) if (!(key in input)) throw localError('invalid-input');
  const result = {};
  for (const key of Object.keys(input).sort()) {
    const spec = feedbackTool.inputSchema.properties[key], value = input[key];
    if (!spec || typeof value !== 'string' || !value.trim() ||
        (spec.maxLength && value.trim().length > spec.maxLength) ||
        (spec.enum && !spec.enum.includes(value)) || (spec.pattern && !new RegExp(spec.pattern).test(value))) throw localError('invalid-input');
    if (/-----BEGIN [A-Z ]*PRIVATE KEY-----|\b(?:sk-|ghp_|gho_|github_pat_|xox[abpr]-|AKIA|hs_)[A-Za-z0-9_-]{12,}|\bBearer\s+[A-Za-z0-9._~+/-]{20,}/i.test(value)) throw localError('secret-detected');
    result[key] = value;
  }
  if ([result.friction, result.improvement].some(value => /^(n\/?a|none|nothing|no issues?|ok|fine|-+|\.+)$/i.test(value.trim()))) throw localError('empty-feedback');
  return result;
}
export function category(error) {
  const code = error?.code ?? error?.cause?.code;
  return [400,401,403,404,408,429,500,502,503,504].includes(code) ? String(code) : error?.authFailure ? 'authentication' : 'unavailable';
}
export class Outbox {
  constructor(home = homedir()) { this.home = home; this.directory = join(home, '.config/hindsight/outbox'); }
  async prepare() {
    let path = this.home;
    for (const segment of ['.config', 'hindsight', 'outbox']) {
      path = join(path, segment);
      await mkdir(path, { mode: 0o700 }).catch(error => { if (error.code !== 'EEXIST') throw error; });
      const info = await lstat(path);
      if (!info.isDirectory() || info.uid !== process.getuid() || (segment !== '.config' && (info.mode & 0o777) !== 0o700)) throw localError('unsafe-outbox');
    }
  }
  path(id) { return join(this.directory, createHash('sha256').update(id).digest('hex') + '.json'); }
  async read(id) {
    await this.prepare();
    const handle = await open(this.path(id), constants.O_RDONLY | constants.O_NOFOLLOW);
    try {
      const info = await handle.stat();
      if (!info.isFile() || info.uid !== process.getuid() || (info.mode & 0o777) !== 0o600 || info.size > 12000) throw localError('unsafe-outbox');
      const data = validated(JSON.parse(await handle.readFile('utf8')));
      if (data.request_id !== id) throw localError('outbox-identity-mismatch');
      return data;
    } finally { await handle.close(); }
  }
  async save(input) {
    const data = validated(input), serialized = JSON.stringify(data);
    if (Buffer.byteLength(serialized) > 12000) throw localError('outbox-size-limit');
    await this.prepare();
    try {
      const existing = await this.read(data.request_id);
      if (JSON.stringify(existing) !== serialized) throw localError('request-id-conflict');
      return data;
    } catch (error) { if (error.code !== 'ENOENT') throw error; }
    if ((await readdir(this.directory)).length >= 100) throw localError('outbox-full');
    const temporary = join(this.directory, '.pending-' + randomUUID());
    const handle = await open(temporary, constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | constants.O_NOFOLLOW, 0o600);
    try {
      await handle.writeFile(serialized); await handle.sync(); await handle.close();
      // Hard-link publication is atomic and never overwrites an existing ID.
      // A crash can leave the private temporary link, but never a truncated entry.
      try { await link(temporary, this.path(data.request_id)); }
      catch (error) {
        if (error.code !== 'EEXIST') throw error;
        const existing = await this.read(data.request_id);
        if (JSON.stringify(existing) !== serialized) throw localError('request-id-conflict');
      }
    } finally {
      await handle.close().catch(() => {});
      await unlink(temporary).catch(error => { if (error.code !== 'ENOENT') throw error; });
    }
    return data;
  }
  async remove(id) { await unlink(this.path(id)).catch(error => { if (error.code !== 'ENOENT') throw error; }); }
}
export async function connectRemote() {
  const auth = spawnSync(`${homedir()}/.local/bin/hindsight-auth-headers`, [], {
    env: { HOME: homedir(), PATH: '/usr/bin:/bin', CLAUDE_CODE_MCP_SERVER_NAME: 'hindsight', CLAUDE_CODE_MCP_SERVER_URL: endpoint },
    encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'], timeout: 5000, maxBuffer: 16384,
  });
  if (auth.status !== 0) throw Object.assign(new Error('Authentication helper failed'), { authFailure: true });
  let headers;
  try { headers = JSON.parse(auth.stdout); } catch { throw Object.assign(new Error('Invalid authentication helper output'), { authFailure: true }); }
  if (Object.keys(headers).length !== 1 || typeof headers.Authorization !== 'string' || !headers.Authorization.startsWith('Bearer ')) throw Object.assign(new Error('Invalid authentication helper output'), { authFailure: true });
  const remote = new Client({ name: 'hindsight-mac-bridge', version: '1.0.0' }, { capabilities: {} });
  const fixedFetch = async (input, init = {}) => {
    const destination = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
    if (destination !== endpoint) throw new Error('Unexpected destination');
    const timeout = AbortSignal.timeout(30000);
    return fetch(input, { ...init, redirect: 'error', signal: init.signal ? AbortSignal.any([init.signal, timeout]) : timeout });
  };
  try {
    await remote.connect(new StreamableHTTPClientTransport(new URL(endpoint), { requestInit: { headers, redirect: 'error' }, fetch: fixedFetch }));
    const catalog = await remote.listTools();
    if (catalog.nextCursor || catalog.tools.filter(tool => tool.name === 'submit_feedback').length !== 1) throw new Error('Expected tool missing');
    return remote;
  } catch (error) { await remote.close().catch(() => {}); throw error; }
}
export function createBridge({ connect = connectRemote, outbox = new Outbox(), warn = message => process.stderr.write(message + '\n') } = {}) {
  let remote, pending;
  const clients = new Set();
  const connection = () => pending ??= connect().then(client => { remote = client; clients.add(client); return client; }).finally(() => { pending = undefined; });
  const server = new Server({ name: 'hindsight-mac-bridge', version: '1.0.0' }, { capabilities: { tools: {} } });
  server.setRequestHandler(ListToolsRequestSchema, async () => ({ tools: [feedbackTool] }));
  const submit = async input => {
    let data;
    try { data = await outbox.save(input); }
    catch (error) {
      const allowed = ['invalid-input', 'secret-detected', 'empty-feedback', 'outbox-size-limit', 'request-id-conflict', 'outbox-full', 'unsafe-outbox', 'outbox-identity-mismatch'];
      const reason = allowed.includes(error.localCategory) ? error.localCategory : 'outbox-unavailable';
      return { isError: true, content: [{ type: 'text', text: `Feedback not sent [${reason}]. No automatic retry.` }] };
    }
    let result;
    try {
      const client = remote ?? await connection();
      result = await client.callTool({ name: 'submit_feedback', arguments: data });
    } catch (error) {
      // Connection failure does not close the shared client underneath other calls.
      remote = undefined;
      return { isError: true, content: [{ type: 'text', text: `HindSight delivery failed [${category(error)}]. Feedback retained in the private outbox. Fix access, then manually replay the same request_id; no automatic retry.` }] };
    }
    const storageUnavailable = result.isError && result.content?.some(item => item.type === 'text' && item.text.startsWith('Storage unavailable;'));
    if (!storageUnavailable) {
      try { await outbox.remove(data.request_id); }
      catch { warn('HindSight response received; local outbox cleanup failed. Delivery status is unchanged; manual cleanup is needed.'); }
    }
    return result;
  };

  server.setRequestHandler(CallToolRequestSchema, request => {
    if (request.params.name !== 'submit_feedback') throw new McpError(ErrorCode.MethodNotFound, 'Unknown HindSight tool');
    return submit(request.params.arguments);
  });
  return {
    server, submit,
    // Best-effort startup check never gates local initialization or discovery.
    probe: () => connection().catch(error => { warn(`HindSight remote unavailable [${category(error)}]; submit_feedback remains available; check credentials and remote catalog.`); }),
    replay: async id => submit(await outbox.read(id)),
    close: async () => { await server.close(); await Promise.allSettled([...clients].map(client => client.close())); },
  };
}
async function main() {
  const bridge = createBridge();
  const args = process.argv.slice(2);
  if (args.length === 2 && args[0] === '--replay' && /^[A-Za-z0-9._:-]{8,128}$/.test(args[1])) {
    const result = await bridge.replay(args[1]);
    process.stderr.write(result.isError ? 'HindSight replay rejected or unavailable; check delivery status before replaying.\n' : 'HindSight replay recorded.\n');
    await bridge.close(); process.exitCode = result.isError ? 1 : 0; return;
  }
  if (args.length) throw new Error('Use no arguments, or --replay REQUEST_ID');
  await bridge.server.connect(new StdioServerTransport());
  void bridge.probe();
  let closing = false;
  const close = async () => {
    if (closing) return; closing = true;
    const deadline = setTimeout(() => process.exit(0), 1500); deadline.unref();
    try { await bridge.close(); } catch { process.stderr.write('HindSight shutdown failed; diagnostics suppressed.\n'); }
    process.exit(0);
  };
  process.once('SIGTERM', close); process.once('SIGINT', close); process.stdin.once('end', close);
}
if (process.argv[1] && pathToFileURL(resolve(process.argv[1])).href === import.meta.url) {
  main().catch(() => { process.stderr.write('HindSight bridge failed; diagnostics suppressed.\n'); process.exitCode = 1; });
}
