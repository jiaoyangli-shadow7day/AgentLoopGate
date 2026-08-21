import { resolve } from 'node:path'
import { Context } from '@deepseek-ai/cordis'
import { CallId } from '@deepseek-ai/dsh-llm'
import SessionStore, { SessionId } from '@deepseek-ai/dsh-session'
import LocalSubprocessRuntime from '@deepseek-ai/dsh-subprocess-local'
import SystemPrompt from '@deepseek-ai/dsh-system-prompt'
import ToolRuntime from '@deepseek-ai/dsh-tools'
import { afterEach, describe, expect, it } from 'vitest'
import * as observerPlugin from '../src/observer.js'
import AgentLoopGateProvider from '../src/provider.js'
import { AgentLoopGateService } from '../src/service.js'
import type {
  BridgeActor,
  EventBatchRequest,
  JsonRecord,
  ObserverStatus,
  TraceSyncRequest,
} from '../src/protocol.js'
import * as toolsPlugin from '../src/tools.js'

class FixtureGate extends AgentLoopGateService {
  batches: EventBatchRequest[] = []

  async health(): Promise<JsonRecord> { return { core: 'ready' } }
  async validateContract(): Promise<JsonRecord> { return { valid: true } }
  async checkCandidate(candidateId: string): Promise<JsonRecord> { return { candidate_id: candidateId } }
  async explainDecision(decisionId: string): Promise<JsonRecord> { return { decision_id: decisionId } }
  async ingestEvents(request: EventBatchRequest, _actor?: BridgeActor): Promise<JsonRecord> {
    this.batches.push(request)
    return { accepted: request.events.length }
  }
  async syncTrace(_request: TraceSyncRequest, _actor?: BridgeActor): Promise<JsonRecord> {
    return { source_trace_id: 'DSH_LIFECYCLE', evidence_status: 'verified' }
  }
  updateObserverStatus(_status: ObserverStatus): void {}
}

const contexts: Context[] = []

afterEach(async () => {
  await Promise.all(contexts.splice(0).map(async ctx => { await ctx.fiber.dispose() }))
})

describe('plugin lifecycle', () => {
  it('removes all four tools when the tool fiber unloads', async () => {
    const ctx = new Context()
    contexts.push(ctx)
    await ctx.plugin(SystemPrompt)
    await ctx.plugin(ToolRuntime)
    await ctx.plugin(FixtureGate)
    const fiber = await ctx.plugin(toolsPlugin, { timeoutMs: 1_000 })

    expect(agentLoopGateToolNames(ctx)).toHaveLength(4)
    await fiber.dispose()
    expect(agentLoopGateToolNames(ctx)).toEqual([])
  })

  it('removes observer listeners when its fiber unloads', async () => {
    const ctx = new Context()
    contexts.push(ctx)
    await ctx.plugin(SessionStore)
    await ctx.plugin(FixtureGate)
    const fiber = await ctx.plugin(observerPlugin, {
      live: true,
      backfillOnStart: true,
      ingestMode: 'reference',
      persistenceKind: 'memory',
      maxBatchEvents: 1,
      maxBufferEvents: 10,
      sourceRevision: 'deepseek-harness@fixture',
    })
    const gate = ctx.reflect._getImpl('agentLoopGate')?.value as FixtureGate
    const session = ctx.sessions.create(SessionId('unload-observer'), {
      meta: { cwd: process.cwd() },
    })
    session.append('turn/start', { turn: 1 })
    await ctx.sessions.flush(session)
    await settle()
    expect(gate.batches).toHaveLength(1)

    await fiber.dispose()
    const batchesAtUnload = gate.batches.length
    session.append('turn/end', { turn: 1, reason: { kind: 'completed' } })
    await ctx.sessions.flush(session)
    await settle()
    expect(gate.batches).toHaveLength(batchesAtUnload)
  })

  it('terminates the persistent Python bridge and removes its service on unload', async () => {
    const ctx = new Context()
    contexts.push(ctx)
    await ctx.plugin(LocalSubprocessRuntime)
    const projectRoot = resolve(import.meta.dirname, '../../..')
    const fiber = await ctx.plugin(AgentLoopGateProvider, {
      projectRoot,
      bridgeCommand: 'uv',
      bridgeArgs: ['run', 'agentloopgate'],
      requestTimeoutMs: 5_000,
      shutdownGraceMs: 1_000,
      stderrMaxBytes: 65_536,
    })
    const service = ctx.get('agentLoopGate')
    const runtime = ctx.reflect._getImpl('subprocess')?.value as { live: Set<unknown> }

    await expect(service?.health()).resolves.toMatchObject({ core: 'ready' })
    expect(runtime.live.size).toBe(1)
    await fiber.dispose()

    expect(runtime.live.size).toBe(0)
    expect(ctx.get('agentLoopGate')).toBeUndefined()
    await expect(service?.health()).rejects.toThrow('disposed')
  })

  it('contains a crashed bridge without interrupting the native Session', async () => {
    const ctx = new Context()
    contexts.push(ctx)
    await ctx.plugin(SessionStore)
    await ctx.plugin(SystemPrompt)
    await ctx.plugin(ToolRuntime)
    await ctx.plugin(LocalSubprocessRuntime)
    await ctx.plugin(AgentLoopGateProvider, {
      projectRoot: resolve(import.meta.dirname, '../../..'),
      bridgeCommand: 'false',
      bridgeArgs: [],
      requestTimeoutMs: 1_000,
      shutdownGraceMs: 100,
      stderrMaxBytes: 4_096,
    })
    await ctx.plugin(toolsPlugin, { timeoutMs: 1_000 })
    await ctx.plugin(observerPlugin, {
      live: true,
      backfillOnStart: true,
      ingestMode: 'reference',
      persistenceKind: 'memory',
      maxBatchEvents: 1,
      maxBufferEvents: 10,
      sourceRevision: 'deepseek-harness@fixture',
    })
    const session = ctx.sessions.create(SessionId('bridge-crash'), {
      meta: { cwd: process.cwd() },
    })

    expect(() => session.append('turn/start', { turn: 1 })).not.toThrow()
    expect(() => session.append('turn/end', {
      turn: 1,
      reason: { kind: 'completed' },
    })).not.toThrow()
    await expect(ctx.sessions.flush(session)).resolves.toBe(true)
    const status = await ctx.tools.execute({
      signal: new AbortController().signal,
      callId: CallId('crashed-bridge-status'),
      name: 'agentloopgate_status',
      arguments: {},
    })

    expect(session.events.at(-1)?.type).toBe('turn/end')
    expect(status).toMatchObject({
      isError: false,
      value: { available: false, method: 'health' },
    })
  })
})

function agentLoopGateToolNames(ctx: Context): string[] {
  return ctx.tools.schemas()
    .map(schema => schema.name)
    .filter(name => name.startsWith('agentloopgate_'))
    .sort()
}

async function settle(): Promise<void> {
  await new Promise(resolve => setTimeout(resolve, 25))
}
