/** Four default, model-visible, non-privileged AgentLoopGate tools. */

import { createHash } from 'node:crypto'
import type { Context } from '@deepseek-ai/cordis'
import z from '@deepseek-ai/schemastery'
import { defineTool } from '@deepseek-ai/dsh-tools'
import type { BridgeActor, JsonRecord, JsonValue } from './protocol.js'
import './service.js'

export const name = 'agentloopgate-tools'
export const inject = ['agentLoopGate', 'tools']

export interface Config {
  timeoutMs: number
}

export const Config: z<Config> = z.object({
  timeoutMs: z.number().min(1).default(10_000),
})

interface ToolEnvelope {
  available: boolean
  method: string
  result?: JsonRecord
  error?: string
}

const envelopeSchema = {
  type: 'object' as const,
  additionalProperties: false,
  properties: {
    available: { type: 'boolean' as const, required: true },
    method: { type: 'string' as const, required: true },
    result: { type: 'object' as const, additionalProperties: true },
    error: { type: 'string' as const },
  },
} as const

export function apply(ctx: Context, config: Config): void {
  ctx.tools.register(defineTool({
    name: 'agentloopgate_status',
    description: 'Read AgentLoopGate Core and trace-observer readiness. This cannot change governance state.',
    parameters: {},
    output: outputDefinition(),
    timeoutMs: config.timeoutMs,
    async execute(_args, exec) {
      return await safeCall('health', () => ctx.agentLoopGate.health(exec.signal))
    },
  }))

  ctx.tools.register(defineTool({
    name: 'agentloopgate_contract_validate',
    description: 'Validate the project-owned Objective Contract without reading evaluation Final data.',
    parameters: {},
    output: outputDefinition(),
    timeoutMs: config.timeoutMs,
    async execute(_args, exec) {
      return await safeCall(
        'contract.validate',
        () => ctx.agentLoopGate.validateContract(actorFor(exec.agent?.session.id), exec.signal),
      )
    },
  }))

  ctx.tools.register(defineTool({
    name: 'agentloopgate_candidate_check',
    description: 'Check one already registered candidate for protected paths, leakage, risk, and change budget.',
    parameters: {
      candidate_id: {
        type: 'string',
        required: true,
        description: 'Registered AgentLoopGate candidate ID.',
      },
    },
    output: outputDefinition(),
    timeoutMs: config.timeoutMs,
    async execute(args, exec) {
      return await safeCall(
        'candidate.check',
        () => ctx.agentLoopGate.checkCandidate(
          args.candidate_id,
          actorFor(exec.agent?.session.id),
          exec.signal,
        ),
      )
    },
  }))

  ctx.tools.register(defineTool({
    name: 'agentloopgate_decision_explain',
    description: 'Read a redacted Ship, Hold, or Reject explanation without exposing release tasks or Final.',
    parameters: {
      decision_id: {
        type: 'string',
        required: true,
        description: 'AgentLoopGate Decision ID.',
      },
    },
    output: outputDefinition(),
    timeoutMs: config.timeoutMs,
    async execute(args, exec) {
      return await safeCall(
        'decision.explain',
        () => ctx.agentLoopGate.explainDecision(
          args.decision_id,
          actorFor(exec.agent?.session.id),
          exec.signal,
        ),
      )
    },
  }))
}

function outputDefinition() {
  return {
    schema: envelopeSchema,
    render: (_args: unknown, value: JsonValue) => [{ type: 'text' as const, text: JSON.stringify(value) }],
  }
}

async function safeCall(method: string, operation: () => Promise<JsonRecord>): Promise<ToolEnvelope> {
  try {
    return { available: true, method, result: await operation() }
  } catch (error: unknown) {
    return {
      available: false,
      method,
      error: error instanceof Error ? error.message : String(error),
    }
  }
}

function actorFor(sessionId: unknown): BridgeActor | undefined {
  if (sessionId === undefined) return undefined
  const hash = createHash('sha256').update(String(sessionId)).digest('hex')
  return { type: 'dsh_plugin', session_id_hash: `sha256:${hash}` }
}

export default { name, inject, Config, apply }
