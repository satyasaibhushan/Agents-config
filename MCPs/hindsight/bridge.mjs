// Config-launched bridge. SDK transports handle MCP framing and HTTP sessions.
import { spawnSync } from 'node:child_process';
import { homedir } from 'node:os';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js';
import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { CallToolRequestSchema, ListToolsRequestSchema, ErrorCode, McpError } from '@modelcontextprotocol/sdk/types.js';

const endpoint = 'https://hindsight.bhushan.fun/api/mcp';
const helper = `${homedir()}/.local/bin/hindsight-auth-headers`;
let remote;
let local;
let closing = false;
let phase = 'startup';

function fail(error) {
  const numericCodes = new Set([400, 401, 403, 404, 405, 408, 409, 415, 421, 429, 500, 502, 503, 504, -32700, -32600, -32601, -32602, -32603, -32000]);
  const networkCodes = new Set(['ENOTFOUND', 'ECONNREFUSED', 'ECONNRESET', 'ETIMEDOUT', 'UND_ERR_CONNECT_TIMEOUT']);
  let category = 'unspecified';
  if (numericCodes.has(error?.code)) category = String(error.code);
  else if (networkCodes.has(error?.cause?.code)) category = error.cause.code;
  else if (error?.name === 'TimeoutError' || error?.name === 'AbortError') category = error.name;
  process.stderr.write(`HindSight MCP connection failed [phase=${phase}; category=${category}].\n`);
  process.exit(1);
}

async function close() {
  if (closing) return;
  closing = true;
  const deadline = setTimeout(() => process.exit(0), 1500);
  deadline.unref();
  try { await local?.close(); } catch {}
  try { await remote?.close(); } catch {}
  process.exit(0);
}

process.on('uncaughtException', fail);
process.on('unhandledRejection', fail);
process.on('SIGTERM', close);
process.on('SIGINT', close);

try {
  if (process.argv.length !== 2) throw new Error('No runtime arguments accepted');
  // Secret output stays in this private child pipe. Never send it to logs/stdout.
  phase = 'authentication-helper';
  const auth = spawnSync(helper, [], {
    env: {
      HOME: homedir(),
      PATH: '/usr/bin:/bin',
      CLAUDE_CODE_MCP_SERVER_NAME: 'hindsight',
      CLAUDE_CODE_MCP_SERVER_URL: endpoint,
    },
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'ignore'],
    timeout: 5000,
    maxBuffer: 16384,
  });
  if (auth.status !== 0) throw new Error('Authentication helper failed');
  const headers = JSON.parse(auth.stdout);
  if (Object.keys(headers).length !== 1 || typeof headers.Authorization !== 'string' || !headers.Authorization.startsWith('Bearer ')) {
    throw new Error('Invalid helper output');
  }
  const fixedFetch = async (input, init = {}) => {
    const destination = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
    if (destination !== endpoint) throw new Error('Unexpected destination');
    const timeout = AbortSignal.timeout(30000);
    const signal = init.signal ? AbortSignal.any([init.signal, timeout]) : timeout;
    return fetch(input, { ...init, redirect: 'error', signal });
  };
  remote = new Client({ name: 'hindsight-mac-bridge', version: '1.0.0' }, { capabilities: {} });
  const transport = new StreamableHTTPClientTransport(new URL(endpoint), {
    requestInit: { headers, redirect: 'error' },
    fetch: fixedFetch,
    // No authProvider: no OAuth fallback, browser, or credential cache.
  });
  phase = 'remote-initialize';
  await remote.connect(transport);
  phase = 'remote-tool-discovery';
  const catalog = await remote.listTools();
  if (catalog.nextCursor) throw new Error('Unexpected paginated HindSight catalog');
  const tools = catalog.tools.filter(tool => tool.name === 'submit_feedback');
  if (tools.length !== 1) throw new Error('Expected tool missing');
  local = new Server({ name: 'hindsight-mac-bridge', version: '1.0.0' }, { capabilities: { tools: {} } });
  local.setRequestHandler(ListToolsRequestSchema, async () => ({ tools }));
  local.setRequestHandler(CallToolRequestSchema, async request => {
    if (request.params.name !== 'submit_feedback') {
      throw new McpError(ErrorCode.MethodNotFound, 'Unknown HindSight tool');
    }
    try {
      // Exactly one invocation. The bridge does not retry tool calls.
      return await remote.callTool(request.params);
    } catch {
      throw new McpError(ErrorCode.InternalError, 'HindSight tool call failed');
    }
  });
  phase = 'local-stdio-start';
  await local.connect(new StdioServerTransport());
  phase = 'ready';
  process.stdin.on('end', close);
} catch (error) {
  fail(error);
}
