/** Public package entry for the AgentLoopGate DeepSeek Harness Bundle. */

export { BridgeClient, BridgeUnavailableError } from './bridge.js'
export type { BridgeClientConfig } from './bridge.js'
export { AgentLoopGateProvider } from './provider.js'
export type { Config as ProviderConfig } from './provider.js'
export { AgentLoopGateService, SERVICE_VERSION } from './service.js'
export type * from './protocol.js'
