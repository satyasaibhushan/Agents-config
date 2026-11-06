import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, readdir, stat, symlink, rm, writeFile, link, unlink } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { InMemoryTransport } from '@modelcontextprotocol/sdk/inMemory.js';
import { createBridge, Outbox, category } from './bridge.mjs';

const feedback = { request_id: 'offline-check-0001', friction: 'A tool disappears when authentication fails.', improvement: 'Keep the local tool catalog available.', category: 'tooling' };
async function fixture(t) {
  const home = await mkdtemp(join(tmpdir(), 'hindsight-bridge-'));
  t.after(() => rm(home, { recursive: true, force: true }));
  return new Outbox(home);
}

test('initialization and catalog survive invalid auth, with sanitized warning and call error', async t => {
  const outbox = await fixture(t), warnings = [];
  let attempts = 0;
  const bridge = createBridge({ outbox, warn: message => warnings.push(message), connect: async () => { attempts++; throw Object.assign(new Error('Bearer SECRET_PRIVATE_HEADER'), { code: 401 }); } });
  const client = new Client({ name: 'offline-test', version: '1' });
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  await Promise.all([bridge.server.connect(serverTransport), client.connect(clientTransport)]);
  t.after(() => client.close());
  await bridge.probe();
  assert.deepEqual((await client.listTools()).tools.map(tool => tool.name), ['submit_feedback']);
  assert.equal(attempts, 1);
  assert.match(warnings[0], /401.*submit_feedback remains available/);
  const result = await client.callTool({ name: 'submit_feedback', arguments: feedback });
  assert.equal(result.isError, true);
  assert.match(result.content[0].text, /401.*private outbox/);
  assert.equal(attempts, 2, 'one attempt per explicit operation, no retry');
  assert.doesNotMatch(JSON.stringify([warnings, result]), /SECRET_PRIVATE_HEADER/);
  assert.deepEqual(await outbox.read(feedback.request_id), feedback);
});

test('manual replay preserves payload and id after uncertain delivery and removes only success', async t => {
  const outbox = await fixture(t), received = [];
  let fail = true;
  const bridge = createBridge({ outbox, connect: async () => ({
    callTool: async params => { received.push(params); if (fail) throw new Error('uncertain'); return {content:[{type:'text',text:'Already recorded feedback test.'}]}; },
    close: async () => {},
  }) });
  assert.equal((await bridge.submit(feedback)).isError, true);
  fail = false;
  await bridge.replay(feedback.request_id);
  assert.deepEqual(received, [0,1].map(() => ({name:'submit_feedback',arguments:feedback})));
  await assert.rejects(outbox.read(feedback.request_id), {code:'ENOENT'});
});

test('remote application error retains the pending item without automatic replay', async t => {
  const outbox = await fixture(t); let calls = 0;
  const bridge = createBridge({outbox,connect:async()=>({callTool:async()=>{calls++;return {isError:true,content:[{type:'text',text:'Storage unavailable; feedback was NOT recorded.'}]};}})});
  assert.equal((await bridge.submit(feedback)).isError,true);
  assert.equal(calls,1);
  assert.deepEqual(await outbox.read(feedback.request_id),feedback);
});

test('outbox is private, rejects changed payloads, secrets and symlinks', async t => {
  const outbox = await fixture(t);
  await outbox.save(feedback);
  assert.equal((await stat(outbox.directory)).mode & 0o777,0o700);
  assert.equal((await stat(outbox.path(feedback.request_id))).mode & 0o777,0o600);
  await assert.rejects(outbox.save({...feedback,improvement:'Changed payload'}),/request-id-conflict/);
  await assert.rejects(outbox.save({...feedback,request_id:'another-id',friction:'Bearer abcdefghijklmnopqrstuvwxyz12345'}),/secret-detected/);
  assert.equal((await readdir(outbox.directory)).length,1);
  const other = await fixture(t);
  await mkdir(join(other.home,'.config'));
  await symlink(outbox.directory,join(other.home,'.config/hindsight'));
  await assert.rejects(other.save(feedback),/unsafe-outbox/);
});

test('outbox capacity and per-entry size are bounded and do not overwrite existing entries', async t => {
  const outbox = await fixture(t);
  for (let i=0;i<100;i++) await outbox.save({...feedback,request_id:`capacity-${String(i).padStart(4,'0')}`});
  await assert.rejects(outbox.save({...feedback,request_id:'capacity-overflow'}),/outbox-full/);
  await outbox.save({...feedback,request_id:'capacity-0000'});
  assert.equal((await readdir(outbox.directory)).length,100);
  assert.equal(category(new Error('secret diagnostic')),'unavailable');
});


test('real stdio starts with a missing auth helper and keeps protocol-only stdout', async t => {
  const outbox = await fixture(t);
  const transport = new StdioClientTransport({command:process.execPath,args:[fileURLToPath(new URL('./bridge.mjs',import.meta.url))],env:{HOME:outbox.home,PATH:'/usr/bin:/bin'},stderr:'pipe'});
  const client = new Client({name:'stdio-test',version:'1'});
  let diagnostics = '';
  transport.stderr.on('data',chunk=>{diagnostics+=chunk;});
  await client.connect(transport);
  t.after(()=>client.close());
  assert.deepEqual((await client.listTools()).tools.map(tool=>tool.name),['submit_feedback']);
  const result=await client.callTool({name:'submit_feedback',arguments:feedback});
  assert.equal(result.isError,true);
  assert.match(result.content[0].text,/authentication/);
  assert.match(diagnostics,/submit_feedback remains available/);
  assert.deepEqual(await outbox.read(feedback.request_id),feedback);
});


test('terminal remote rejections are removed while local no-op input never sends', async t => {
  const outbox=await fixture(t); let calls=0;
  for(const message of ['Rejected: empty or no-op feedback is not recorded.','Rejected: feedback appears to contain a secret.','Conflict (409): request_id was already used.']) {
    const bridge=createBridge({outbox,connect:async()=>({callTool:async()=>{calls++;return {isError:true,content:[{type:'text',text:message}]};}})});
    assert.equal((await bridge.submit(feedback)).isError,true);
    await assert.rejects(outbox.read(feedback.request_id),{code:'ENOENT'});
  }
  const bridge=createBridge({outbox,connect:async()=>{throw Error('Must not connect');}});
  const result=await bridge.submit({...feedback,friction:'n/a'});
  assert.match(result.content[0].text,/empty-feedback/);
  assert.equal(calls,3);
  assert.deepEqual(await readdir(outbox.directory),[]);
});

test('concurrent same-ID delivery keeps both authoritative successes and cleanup is idempotent', async t => {
  const outbox=await fixture(t); let started=0,release;
  const ready=new Promise(resolve=>{release=resolve;});
  const bridge=createBridge({outbox,connect:async()=>({callTool:async()=>{if(++started===2)release();await ready;return {content:[{type:'text',text:'Recorded'}]};}})});
  const results=await Promise.all([bridge.submit(feedback),bridge.submit(feedback)]);
  assert.ok(results.every(result=>!result.isError));
  await outbox.remove(feedback.request_id);
  assert.deepEqual(await readdir(outbox.directory),[]);
});

test('cleanup failure does not misreport a successful delivery or close its shared connection', async t => {
  const outbox=await fixture(t),warnings=[]; let closed=0;
  outbox.remove=async()=>{throw Object.assign(Error('private storage details'),{code:'EACCES'});};
  const bridge=createBridge({outbox,warn:message=>warnings.push(message),connect:async()=>({callTool:async()=>({content:[{type:'text',text:'Recorded'}]}),close:async()=>{closed++;}})});
  assert.equal((await bridge.submit(feedback)).isError,undefined);
  assert.equal(closed,0);
  assert.match(warnings[0],/cleanup failed/);
  assert.doesNotMatch(warnings[0],/private storage details/);
});

test('interrupted temporary writes do not poison request IDs and published links remain readable', async t => {
  const outbox=await fixture(t); await outbox.prepare();
  await writeFile(join(outbox.directory,'.pending-interrupted'),'{"request_id":',{mode:0o600});
  await outbox.save(feedback);
  assert.deepEqual(await outbox.read(feedback.request_id),feedback);
  const temporary=join(outbox.directory,'.pending-published');
  await link(outbox.path(feedback.request_id),temporary);
  assert.deepEqual(await outbox.read(feedback.request_id),feedback);
  await unlink(temporary);
});

test('local failures expose only stable sanitized categories', async t => {
  const outbox=await fixture(t); const bridge=createBridge({outbox,connect:async()=>{throw Error('Must not connect');}});
  for(const [input,reason] of [[{},'invalid-input'],[{...feedback,friction:'Bearer abcdefghijklmnopqrstuvwxyz12345'},'secret-detected']]) {
    assert.match((await bridge.submit(input)).content[0].text,new RegExp(reason));
  }
  await outbox.save(feedback);
  assert.match((await bridge.submit({...feedback,improvement:'Changed'})).content[0].text,/request-id-conflict/);
  outbox.save=async()=>{throw Error('sensitive filesystem path');};
  const result=await bridge.submit(feedback);
  assert.match(result.content[0].text,/outbox-unavailable/);
  assert.doesNotMatch(result.content[0].text,/sensitive/);
});
