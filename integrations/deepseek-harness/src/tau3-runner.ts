/** One-turn runner used only by the τ³ banking reference validation adapter. */

import type { Context } from '@deepseek-ai/cordis'
import z from '@deepseek-ai/schemastery'
import { installModelSelection } from '@deepseek-ai/dsh-agent'
import type { ModelSelectionRef } from '@deepseek-ai/dsh-agent'
import type {} from '@deepseek-ai/dsh-agent-default-model'
import { createUserMessage } from '@deepseek-ai/dsh-llm'
import { SessionId } from '@deepseek-ai/dsh-session'
import type { SessionEvent } from '@deepseek-ai/dsh-session'
import type {} from '@deepseek-ai/dsh-session-persistence'
import type {} from '@deepseek-ai/cordis-plugin-loader'
import type {} from '@deepseek-ai/dsh-cmdline'

export const name = 'agentloopgate-tau3-runner'
export const inject = [
  'agentDefaultModel',
  'agents',
  'sessions',
  'sessionPersistence',
]

export interface Config {
  prompt: string
  sessionId: string
  temperature: number
  maxTokens: number
}

export const Config: z<Config> = z.object({
  prompt: z.string().required(),
  sessionId: z.string().required(),
  temperature: z.number().min(0).required(),
  maxTokens: z.number().step(1).min(1).required(),
})

export interface Tau3TurnEnvelope {
  protocol_version: '1.1'
  event_seq_start: number
  event_seq_end: number
  final_response: string
  finish_reason: string | null
  input_tokens: number
  cache_read_tokens: number
  output_tokens: number
  provider_retry_count: number
}

interface RunnerIo {
  stdout: { write(chunk: string): unknown }
  stderr: { write(chunk: string): unknown }
  exit(code: number): void
}

export const internals: { stdout: RunnerIo['stdout']; stderr: RunnerIo['stderr'] } = {
  stdout: process.stdout,
  stderr: process.stderr,
}

export function summarizeTau3Interval(
  events: readonly SessionEvent[],
  firstSeq: number,
): Tau3TurnEnvelope {
  let finalResponse = ''
  let finishReason: string | null = null
  let inputTokens = 0
  let cacheReadTokens = 0
  let outputTokens = 0
  let providerRetryCount = 0
  let eventSeqEnd = firstSeq - 1
  for (const event of events) {
    if (event.seq < firstSeq) continue
    eventSeqEnd = Math.max(eventSeqEnd, event.seq)
    if (event.type === 'assistant/message') {
      const text = event.data.message.content
        .filter(block => block.type === 'text')
        .map(block => block.text)
        .join('')
      if (text !== '') finalResponse = text
      inputTokens += event.data.usage?.inputTokens ?? 0
      cacheReadTokens += event.data.usage?.cacheReadTokens ?? 0
      outputTokens += event.data.usage?.outputTokens ?? 0
    }
    // dsh-llm-retry owns this durable event. Count the scheduled retry, not
    // retry-started, so a cancelled wait is still retained as attempted work.
    if (String(event.type) === 'llm/retry') providerRetryCount += 1
    if (event.type === 'turn/end') finishReason = event.data.reason.kind
  }
  return {
    protocol_version: '1.1',
    event_seq_start: firstSeq,
    event_seq_end: eventSeqEnd,
    final_response: finalResponse,
    finish_reason: finishReason,
    input_tokens: inputTokens,
    cache_read_tokens: cacheReadTokens,
    output_tokens: outputTokens,
    provider_retry_count: providerRetryCount,
  }
}

async function run(ctx: Context, config: Config, io: RunnerIo): Promise<void> {
  await ctx.get('loader')?.await()
  const agents = ctx.get('agents')
  const defaultModel = ctx.get('agentDefaultModel')
  const sessions = ctx.get('sessions')
  const persistence = ctx.get('sessionPersistence')
  if (
    agents === undefined
    || defaultModel === undefined
    || sessions === undefined
    || persistence === undefined
  ) return

  const sessionId = SessionId(config.sessionId)
  const selection = defaultModel.currentSelection()
  const setup = (agentCtx: Context): void => {
    const selected: ModelSelectionRef = { current: selection, assembled: undefined }
    installModelSelection(agentCtx, selected)
    agentCtx.on('agent/request', async (_payload, next) => ({
      ...await next(),
      temperature: config.temperature,
      maxTokens: config.maxTokens,
    }))
  }
  const persisted = (await persistence.list()).some(header => header.id === sessionId)
  const handle = persisted
    ? await agents.resume({
        resumeSessionId: sessionId,
        agentOptions: {
          provider: selection.provider,
          model: selection.model,
          maxTokens: config.maxTokens,
        },
        setup,
      })
    : await agents.create({
        sessionId,
        meta: { cwd: process.cwd() },
        agentOptions: {
          provider: selection.provider,
          model: selection.model,
          maxTokens: config.maxTokens,
        },
        setup,
      })
  const agent = handle.agent
  await agent.whenIdle()
  const firstSeq = agent.session.seq
  agent.followup(createUserMessage({
    content: [{ type: 'text', text: config.prompt }],
    source: { kind: 'user' },
  }))
  await agent.whenIdle()
  await sessions.flush(agent.session)
  const outcome = summarizeTau3Interval(agent.session.events, firstSeq)
  io.stdout.write(`${JSON.stringify(outcome)}\n`)
  if (outcome.finish_reason !== 'completed') {
    io.stderr.write(`agentloopgate-tau3-runner: turn ended as ${String(outcome.finish_reason)}\n`)
  }
  io.exit(outcome.finish_reason === 'completed' ? 0 : 1)
}

export function apply(ctx: Context, config: Config): void {
  const exit = ctx.get('appExit')
  if (exit === undefined) {
    throw new Error('agentloopgate-tau3-runner requires the CLI appExit service')
  }
  const io: RunnerIo = { stdout: internals.stdout, stderr: internals.stderr, exit }
  void run(ctx, config, io).catch((error: unknown) => {
    io.stderr.write(
      `agentloopgate-tau3-runner: ${error instanceof Error ? error.message : String(error)}\n`,
    )
    io.exit(1)
  })
}

export default { name, inject, Config, apply }
