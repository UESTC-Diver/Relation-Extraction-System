import { describe, expect, it } from 'vitest'
import { RULE_BASE_LABEL, ruleLabel } from '../src/utils/labels'

describe('ruleLabel', () => {
  it('映射已知抽取来源', () => {
    expect(ruleLabel('pattern')).toBe('句式模板')
    expect(ruleLabel('coref')).toBe('指代消解')
    expect(ruleLabel('chain')).toBe('主语链')
    expect(ruleLabel('manual')).toBe('人工校正')
  })

  it('未知来源回退到原始 key，空值回退到占位符', () => {
    expect(ruleLabel('custom-rule')).toBe('custom-rule')
    expect(ruleLabel('')).toBe('—')
    expect(ruleLabel(undefined)).toBe('—')
  })

  it('人工校正标签已登记', () => {
    expect(RULE_BASE_LABEL.manual).toBe('人工校正')
  })
})
