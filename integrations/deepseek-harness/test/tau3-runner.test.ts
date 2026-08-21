import { describe, expect, it } from 'vitest'
import type { SessionEvent } from '@deepseek-ai/dsh-session'
import { summarizeTau3Interval } from '../src/tau3-runner.js'

describe('τ³ one-turn runner', () => {
  it('returns only the owned interval and sums native token usage', () => {
    const events = [
      {
        type: 'llm/retry',
        seq: 3,
        time: 3,
        data: {},
        ignorable: true,
      },
      {
        type: 'assistant/message',
        seq: 1,
        time: 1,
        data: {
          turn: 0,
          step: 0,
          message: { role: 'assistant', content: [{ type: 'text', text: 'old' }] },
          usage: { inputTokens: 99, outputTokens: 99 },
        },
      },
      {
        type: 'assistant/message',
        seq: 4,
        time: 4,
        data: {
          turn: 1,
          step: 0,
          message: { role: 'assistant', content: [{ type: 'text', text: '{"content":"ok"}' }] },
          usage: { inputTokens: 12, cacheReadTokens: 7, outputTokens: 3 },
        },
      },
      {
        type: 'turn/end',
        seq: 5,
        time: 5,
        data: { turn: 1, reason: { kind: 'completed' } },
      },
    ] as SessionEvent[]

    expect(summarizeTau3Interval(events, 2)).toEqual({
      protocol_version: '1.1',
      event_seq_start: 2,
      event_seq_end: 5,
      final_response: '{"content":"ok"}',
      finish_reason: 'completed',
      input_tokens: 12,
      cache_read_tokens: 7,
      output_tokens: 3,
      provider_retry_count: 1,
    })
  })
})
