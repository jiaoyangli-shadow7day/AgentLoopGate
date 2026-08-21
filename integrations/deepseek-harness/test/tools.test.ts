import { Context } from '@deepseek-ai/cordis'
import { CallId } from '@deepseek-ai/dsh-llm'
import SystemPrompt from '@deepseek-ai/dsh-system-prompt'
import ToolRuntime from '@deepseek-ai/dsh-tools'
import { afterEach, describe, expect, it } from 'vitest'
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
  calls: Array<[string, string | undefined]> = []

  async health(): Promise<JsonRecord> {
    this.calls.push(['health', undefined])
    return { core: 'ready' }
  }

  async validateContract(): Promise<JsonRecord> {
    this.calls.push(['contract.validate', undefined])
    return { valid: true }
  }

  async checkCandidate(candidateId: string): Promise<JsonRecord> {
    this.calls.push(['candidate.check', candidateId])
    return { candidate_id: candidateId, disposition: 'pass' }
  }

  async explainDecision(decisionId: string): Promise<JsonRecord> {
    this.calls.push(['decision.explain', decisionId])
    return { decision_id: decisionId, decision: 'HOLD' }
  }

  async ingestEvents(
    _request: EventBatchRequest,
    _actor?: BridgeActor,
  ): Promise<JsonRecord> {
    return { accepted: 1 }
  }

  async syncTrace(
    _request: TraceSyncRequest,
    _actor?: BridgeActor,
  ): Promise<JsonRecord> {
    return { evidence_status: 'verified' }
  }

  updateObserverStatus(_status: ObserverStatus): void {}
}

const contexts: Context[] = []

afterEach(async () => {
  await Promise.all(contexts.splice(0).map(async ctx => { await ctx.fiber.dispose() }))
})

async function setup(): Promise<Context> {
  const ctx = new Context()
  contexts.push(ctx)
  await ctx.plugin(SystemPrompt)
  await ctx.plugin(ToolRuntime)
  await ctx.plugin(FixtureGate)
  await ctx.plugin(toolsPlugin, { timeoutMs: 1_000 })
  return ctx
}

describe('AgentLoopGate model tools', () => {
  it('registers exactly the four safe tools and no privileged surface', async () => {
    const ctx = await setup()
    const names = ctx.tools.schemas().map(schema => schema.name).sort()

    expect(names).toEqual([
      'agentloopgate_candidate_check',
      'agentloopgate_contract_validate',
      'agentloopgate_decision_explain',
      'agentloopgate_status',
    ])
    expect(names).not.toContain('agentloopgate_propose')
    expect(names.every(name => !name.includes('promote') && !name.includes('final'))).toBe(true)
  })

  it('routes candidate check and decision explain through the Cordis service', async () => {
    const ctx = await setup()
    const signal = new AbortController().signal
    const candidate = await ctx.tools.execute({
      signal,
      callId: CallId('candidate-call'),
      name: 'agentloopgate_candidate_check',
      arguments: { candidate_id: 'C_001' },
    })
    const decision = await ctx.tools.execute({
      signal,
      callId: CallId('decision-call'),
      name: 'agentloopgate_decision_explain',
      arguments: { decision_id: 'D_001' },
    })

    expect(candidate).toMatchObject({
      isError: false,
      value: {
        available: true,
        method: 'candidate.check',
        result: { candidate_id: 'C_001', disposition: 'pass' },
      },
    })
    expect(decision).toMatchObject({
      isError: false,
      value: {
        available: true,
        method: 'decision.explain',
        result: { decision_id: 'D_001', decision: 'HOLD' },
      },
    })
    expect((ctx.agentLoopGate as FixtureGate).calls).toContainEqual([
      'candidate.check',
      'C_001',
    ])
  })

  it('contains service failure as an unavailable read result', async () => {
    const ctx = await setup()
    ;(ctx.agentLoopGate as FixtureGate).health = async () => {
      throw new Error('bridge offline')
    }
    const result = await ctx.tools.execute({
      signal: new AbortController().signal,
      callId: CallId('status-call'),
      name: 'agentloopgate_status',
      arguments: {},
    })

    expect(result).toMatchObject({
      isError: false,
      value: { available: false, method: 'health', error: 'bridge offline' },
    })
  })
})
