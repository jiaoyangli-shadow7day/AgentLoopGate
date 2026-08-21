/** Persistent stdio JSONL client over DeepSeek Harness' managed subprocess seam. */

import { randomUUID } from 'node:crypto'
import type { Readable, Writable } from 'node:stream'
import type { SubprocessHandle, SubprocessRuntime } from '@deepseek-ai/dsh-subprocess'
import type {
  BridgeActor,
  BridgeRequest,
  BridgeResponse,
  JsonRecord,
} from './protocol.js'

const MAX_REQUEST_BYTES = 1024 * 1024

export interface BridgeClientConfig {
  projectRoot: string
  bridgeCommand: string
  bridgeArgs: string[]
  requestTimeoutMs: number
  shutdownGraceMs: number
  stderrMaxBytes: number
}

interface PendingRequest {
  resolve(response: BridgeResponse): void
  reject(error: Error): void
  dispose(): void
}

export class BridgeUnavailableError extends Error {
  readonly code = 'bridge_unavailable'
}

/** One managed child, started lazily and terminated with its Cordis provider. */
export class BridgeClient {
  private handle: SubprocessHandle | undefined
  private startPromise: Promise<SubprocessHandle> | undefined
  private stdoutBuffer = ''
  private readonly pending = new Map<string, PendingRequest>()
  private disposed = false

  constructor(
    private readonly subprocess: SubprocessRuntime,
    private readonly config: BridgeClientConfig,
  ) {}

  async call(
    method: string,
    payload: JsonRecord,
    actor?: BridgeActor,
    signal?: AbortSignal,
  ): Promise<JsonRecord> {
    if (this.disposed) throw new BridgeUnavailableError('AgentLoopGate bridge is disposed')
    signal?.throwIfAborted()
    const handle = await this.start()
    const request: BridgeRequest = {
      protocol_version: '1.0',
      request_id: `REQ_${randomUUID()}`,
      method,
      payload,
      ...(actor === undefined ? {} : { actor }),
    }
    const line = JSON.stringify(request) + '\n'
    if (Buffer.byteLength(line) > MAX_REQUEST_BYTES + 1) {
      throw new Error('bridge request exceeds the 1 MiB limit')
    }
    const stdin = handle.stdin
    if (stdin === undefined) throw new BridgeUnavailableError('bridge stdin is unavailable')
    return await new Promise<JsonRecord>((resolve, reject) => {
      const timeout = AbortSignal.timeout(this.config.requestTimeoutMs)
      const combined = signal === undefined ? timeout : AbortSignal.any([signal, timeout])
      const onAbort = (): void => {
        this.pending.delete(request.request_id)
        reject(new BridgeUnavailableError('bridge request was cancelled or timed out'))
      }
      combined.addEventListener('abort', onAbort, { once: true })
      const dispose = (): void => { combined.removeEventListener('abort', onAbort) }
      this.pending.set(request.request_id, {
        resolve: (response) => {
          dispose()
          if (!response.ok || response.result === null) {
            const error = response.error
            reject(new Error(error === null ? 'bridge rejected the request' : `${error.code}: ${error.message}`))
            return
          }
          resolve(response.result)
        },
        reject: (error) => { dispose(); reject(error) },
        dispose,
      })
      writeLine(stdin, line).catch((error: unknown) => {
        const pending = this.pending.get(request.request_id)
        if (pending === undefined) return
        this.pending.delete(request.request_id)
        pending.reject(new BridgeUnavailableError(errorMessage(error)))
      })
    })
  }

  async close(): Promise<void> {
    this.disposed = true
    const handle = this.handle ?? await this.startPromise?.catch(() => undefined)
    if (handle !== undefined) {
      handle.stdin?.end()
      handle.terminate()
      await handle.waitForExit()
    }
    this.failAll(new BridgeUnavailableError('AgentLoopGate bridge closed'))
    this.handle = undefined
    this.startPromise = undefined
  }

  private async start(): Promise<SubprocessHandle> {
    if (this.handle !== undefined) return this.handle
    if (this.startPromise !== undefined) return await this.startPromise
    this.startPromise = this.spawn()
    try {
      return await this.startPromise
    } finally {
      this.startPromise = undefined
    }
  }

  private async spawn(): Promise<SubprocessHandle> {
    const executable = await this.subprocess.resolveExecutable(this.config.bridgeCommand)
    const handle = this.subprocess.spawn({
      argv: [
        executable,
        ...this.config.bridgeArgs,
        'bridge',
        'serve',
        '--project',
        this.config.projectRoot,
      ],
      cwd: this.config.projectRoot,
      stdio: {
        stdin: 'pipe',
        stdout: 'pipe',
        stderr: { maxBytes: this.config.stderrMaxBytes },
      },
      graceMs: this.config.shutdownGraceMs,
      env: { PYTHONUNBUFFERED: '1' },
    })
    if (handle.stdout === undefined) {
      handle.terminate()
      throw new BridgeUnavailableError('bridge stdout is unavailable')
    }
    this.handle = handle
    this.readStdout(handle, handle.stdout)
    handle.stdin?.on('error', error => {
      this.childStopped(handle, `bridge stdin failed: ${errorMessage(error)}`)
    })
    void handle.done.then(
      outcome => this.childStopped(
        handle,
        `bridge exited with code ${String(outcome.exitCode)}`,
      ),
      error => this.childStopped(handle, `bridge failed to start: ${errorMessage(error)}`),
    )
    return handle
  }

  private readStdout(handle: SubprocessHandle, stdout: Readable): void {
    stdout.setEncoding('utf8')
    stdout.on('data', (chunk: string) => {
      this.stdoutBuffer += chunk
      while (true) {
        const newline = this.stdoutBuffer.indexOf('\n')
        if (newline < 0) break
        const line = this.stdoutBuffer.slice(0, newline)
        this.stdoutBuffer = this.stdoutBuffer.slice(newline + 1)
        this.acceptLine(handle, line)
      }
      if (Buffer.byteLength(this.stdoutBuffer) > MAX_REQUEST_BYTES) {
        this.childStopped(handle, 'bridge emitted an oversized response')
        handle.terminate()
      }
    })
  }

  private acceptLine(handle: SubprocessHandle, line: string): void {
    let response: BridgeResponse
    try {
      const parsed: unknown = JSON.parse(line)
      if (!isBridgeResponse(parsed)) throw new Error('invalid response fields')
      response = parsed
    } catch (error: unknown) {
      this.childStopped(handle, `bridge emitted invalid JSONL: ${errorMessage(error)}`)
      handle.terminate()
      return
    }
    const pending = this.pending.get(response.request_id)
    if (pending === undefined) return
    this.pending.delete(response.request_id)
    pending.resolve(response)
  }

  private childStopped(handle: SubprocessHandle, message: string): void {
    if (this.handle !== handle) return
    this.handle = undefined
    this.stdoutBuffer = ''
    this.failAll(new BridgeUnavailableError(message))
  }

  private failAll(error: Error): void {
    for (const pending of this.pending.values()) pending.reject(error)
    this.pending.clear()
  }
}

function isBridgeResponse(value: unknown): value is BridgeResponse {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return false
  const record = value as Record<string, unknown>
  return record['protocol_version'] === '1.0'
    && typeof record['request_id'] === 'string'
    && typeof record['ok'] === 'boolean'
    && ('result' in record)
    && ('error' in record)
}

async function writeLine(stdin: Writable, line: string): Promise<void> {
  await new Promise<void>((resolve, reject) => {
    stdin.write(line, (error?: Error | null) => { error === undefined || error === null ? resolve() : reject(error) })
  })
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}
