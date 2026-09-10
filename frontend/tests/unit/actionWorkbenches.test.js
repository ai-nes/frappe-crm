import { describe, expect, it } from 'vitest'
import { ACTION_WORKBENCH_REGISTRY, workbenchFor } from '../../src/components/StudentDecision/workbenches'
describe('action workbench registry', () => {
  it('registers only CALL and EMAIL', () => { expect(ACTION_WORKBENCH_REGISTRY['call-package:v1']).toBeTruthy(); expect(ACTION_WORKBENCH_REGISTRY['message-package:v1']).toBeUndefined() })
  it('fails closed for unknown schemas', () => { expect(workbenchFor({ package: { schema: 'handoff:v1' } })).toBeNull() })
})
