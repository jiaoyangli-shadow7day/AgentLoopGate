import { execFileSync, spawn } from 'node:child_process'
import { mkdtempSync, readFileSync, readdirSync, rmSync } from 'node:fs'
import { createServer } from 'node:http'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const projectRoot = resolve(packageRoot, '..', '..')
const temporary = mkdtempSync(join(tmpdir(), 'agentloopgate-dsh-conformance-'))
const dshHome = join(temporary, 'dsh-home')
const dsh = resolve(packageRoot, 'node_modules/.bin/dsh')
const environment = { ...process.env, DSH_HOME: dshHome }
for (const key of [
  'DEEPSEEK_API_KEY',
  'HTTP_PROXY',
  'HTTPS_PROXY',
  'ALL_PROXY',
  'http_proxy',
  'https_proxy',
  'all_proxy',
]) delete environment[key]
Object.assign(environment, {
  AGENTLOOPGATE_PROJECT_ROOT: temporary,
  AGENTLOOPGATE_BRIDGE_COMMAND: resolve(projectRoot, '.venv/bin/agentloopgate'),
  AGENTLOOPGATE_TAU_PROMPT: '{}',
  AGENTLOOPGATE_TAU_SESSION_ID: 'alg-conformance',
  AGENTLOOPGATE_DSH_SESSION_ROOT: join(temporary, 'native-sessions'),
  AGENTLOOPGATE_DSH_PROVIDER: 'deepseek-official',
  AGENTLOOPGATE_DSH_MODEL: 'deepseek-v4-flash',
  AGENTLOOPGATE_DSH_STREAM_IDLE_TIMEOUT_MS: '300000',
  AGENTLOOPGATE_PROVIDER_MAX_RETRIES: '0',
  AGENTLOOPGATE_PROVIDER_RETRY_DELAY_MS: '500',
  AGENTLOOPGATE_AGENT_TEMPERATURE: '0',
  AGENTLOOPGATE_AGENT_MAX_OUTPUT_TOKENS: '4096',
})

function run(file, args, options = {}) {
  return execFileSync(file, args, {
    cwd: projectRoot,
    env: environment,
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'pipe'],
    ...options,
  })
}

function runAsync(file, args) {
  return new Promise((resolveRun, rejectRun) => {
    const child = spawn(file, args, {
      cwd: projectRoot,
      env: environment,
      stdio: ['ignore', 'pipe', 'pipe'],
    })
    let stdout = ''
    let stderr = ''
    const timeout = setTimeout(() => {
      child.kill('SIGTERM')
      rejectRun(new Error('live banking composition did not exit within 30 seconds'))
    }, 30_000)
    child.stdout.setEncoding('utf8')
    child.stderr.setEncoding('utf8')
    child.stdout.on('data', chunk => { stdout += chunk })
    child.stderr.on('data', chunk => { stderr += chunk })
    child.on('error', error => {
      clearTimeout(timeout)
      rejectRun(error)
    })
    child.on('close', code => {
      clearTimeout(timeout)
      if (code !== 0) {
        rejectRun(new Error(`live banking composition exited ${String(code)}\n${stderr}`))
        return
      }
      resolveRun({ stdout, stderr })
    })
  })
}

async function mockCompletionServer() {
  let requestCount = 0
  const server = createServer((request, response) => {
    request.resume()
    request.on('end', () => {
      requestCount += 1
      response.writeHead(200, { 'content-type': 'text/event-stream' })
      response.write('data: {"choices":[{"delta":{"role":"assistant","content":null,"reasoning_content":""}}]}\n\n')
      response.write('data: {"choices":[{"delta":{"content":"{\\"assistant_message\\":\\"conformance\\"}"}}]}\n\n')
      response.write('data: {"choices":[{"delta":{"content":""},"finish_reason":"stop"}],"usage":{"prompt_tokens":3,"completion_tokens":1}}\n\n')
      response.write('data: [DONE]\n\n')
      response.end()
    })
  })
  await new Promise((resolveListen, rejectListen) => {
    server.once('error', rejectListen)
    server.listen(0, '127.0.0.1', resolveListen)
  })
  const address = server.address()
  if (address === null || typeof address === 'string') throw new Error('mock server has no TCP port')
  return {
    server,
    url: `http://127.0.0.1:${address.port}`,
    requestCount: () => requestCount,
  }
}

let mock
try {
  run('pnpm', ['pack', '--pack-destination', temporary], { cwd: packageRoot })
  const tarball = readdirSync(temporary)
    .filter(name => name.endsWith('.tgz'))
    .map(name => join(temporary, name))[0]
  if (tarball === undefined) throw new Error('pnpm pack did not produce a tarball')

  run(dsh, ['plugin', '--profile', 'headless', 'add', tarball])
  const manifestPath = join(dshHome, 'profiles/headless/package.json')
  const installed = JSON.parse(readFileSync(manifestPath, 'utf8'))
  if (installed.dependencies?.['@agentloopgate/dsh-plugin'] === undefined) {
    throw new Error('plugin dependency was not installed in the fresh profile')
  }
  if (!installed.dsh?.profile?.bundles?.includes('@agentloopgate/dsh-plugin')) {
    throw new Error('plugin Bundle was not added to the fresh profile')
  }

  const composed = run(dsh, ['--profile', 'headless', '--dump-config'])
  for (const row of [
    'agentloopgate-provider',
    'agentloopgate-observer',
    'agentloopgate-tools',
    'session-persistence-jsonl',
    'session-telemetry-otel',
  ]) {
    if (!composed.includes(row)) throw new Error(`composed profile is missing ${row}`)
  }

  const pilotPatch = resolve(projectRoot, 'examples/tau3-banking/dsh-tau3.patch.yml')
  const pilot = run(dsh, [
    '--profile', 'headless', '--patch', pilotPatch, '--dump-config',
  ])
  for (const row of [
    'agentloopgate-tau3-runner',
    'agentloopgate-observer',
    'session-persistence-jsonl',
  ]) {
    if (!pilot.includes(row)) throw new Error(`banking pilot composition is missing ${row}`)
  }
  if (!/- id: headless-runner[\s\S]*?disabled: true/.test(pilot)) {
    throw new Error('banking pilot did not disable the ordinary headless runner')
  }
  if (!/- id: web-search-deepseek[\s\S]*?disabled: true/.test(pilot)) {
    throw new Error('banking pilot left the web-search provider waiting on disabled web')
  }
  if (!pilot.includes(
    'streamIdleTimeoutMs: !!js Number(process.env.AGENTLOOPGATE_DSH_STREAM_IDLE_TIMEOUT_MS)',
  ) || environment.AGENTLOOPGATE_DSH_STREAM_IDLE_TIMEOUT_MS !== '300000') {
    throw new Error('banking pilot did not freeze the DSH stream idle timeout')
  }

  mock = await mockCompletionServer()
  environment.DEEPSEEK_API_KEY = 'conformance-only-key'
  environment.DEEPSEEK_BASE_URL = mock.url
  const live = await runAsync(dsh, [
    '--profile', 'headless', '--patch', pilotPatch,
  ])
  const envelope = JSON.parse(live.stdout.trim())
  if (envelope.protocol_version !== '1.1'
    || envelope.final_response !== '{"assistant_message":"conformance"}'
    || envelope.finish_reason !== 'completed'
    || envelope.input_tokens !== 3
    || envelope.output_tokens !== 1
    || envelope.provider_retry_count !== 0) {
    throw new Error(`unexpected live banking envelope: ${live.stdout.trim()}`)
  }
  if (mock.requestCount() !== 1) {
    throw new Error(`live banking composition made ${String(mock.requestCount())} model requests`)
  }
  const traceRefs = readdirSync(join(temporary, 'runs/trace_refs'))
    .filter(name => name.startsWith('DSH_') && name.endsWith('.json'))
    .map(name => JSON.parse(readFileSync(join(temporary, 'runs/trace_refs', name), 'utf8')))
  if (!traceRefs.some(ref => ref.cursor_complete === true
    && ref.evidence_status === 'verified'
    && ref.event_seq_end >= envelope.event_seq_end)) {
    throw new Error('live banking composition did not persist a complete DSH trace ref')
  }

  run(dsh, ['--profile', 'headless', '--help'])
  run(dsh, [
    'plugin',
    '--profile',
    'headless',
    'remove',
    '@agentloopgate/dsh-plugin',
  ])
  const removed = JSON.parse(readFileSync(manifestPath, 'utf8'))
  if (removed.dependencies?.['@agentloopgate/dsh-plugin'] !== undefined
    || removed.dsh?.profile?.bundles?.includes('@agentloopgate/dsh-plugin')) {
    throw new Error('plugin removal left a profile dependency or Bundle layer')
  }
  const nativeOnly = run(dsh, ['--profile', 'headless', '--dump-config'])
  if (!nativeOnly.includes('session-persistence-jsonl')
    || !nativeOnly.includes('session-telemetry-otel')) {
    throw new Error('native Session Persistence or Telemetry disappeared after removal')
  }
  process.stdout.write('DeepSeek Harness headless Bundle conformance: passed\n')
} finally {
  if (mock !== undefined) {
    await new Promise(resolveClose => mock.server.close(resolveClose))
  }
  rmSync(temporary, { recursive: true, force: true })
}
