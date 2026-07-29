// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { isTrustedIpcSender } from './ipc'

describe('isTrustedIpcSender', () => {
  const sender = (id: number, parent: object | null) =>
    ({ sender: { id }, senderFrame: { parent } }) as Parameters<typeof isTrustedIpcSender>[0]

  it('accepts only the trusted main frame', () => {
    expect(isTrustedIpcSender(sender(7, null), 7)).toBe(true)
    expect(isTrustedIpcSender(sender(8, null), 7)).toBe(false)
    expect(isTrustedIpcSender(sender(7, {}), 7)).toBe(false)
    expect(isTrustedIpcSender({ sender: { id: 7 }, senderFrame: null } as never, 7)).toBe(false)
  })
})
