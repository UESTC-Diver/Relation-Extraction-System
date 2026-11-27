import { describe, expect, it } from 'vitest'
import { buildCsv, buildMarkdown } from '../src/utils/export'

const RESULT = {
  text: '星河科技与华为签署协议。',
  entities: [],
  entity_type_counts: { ORG: 2 },
  relation_type_counts: { sign: 1 },
  stats: { char_count: 12, sentence_count: 1, entity_count: 2, relation_count: 1 },
  relations: [
    {
      head: '星河科技',
      head_canonical: '星河科技',
      head_type: 'ORG',
      relation: 'sign',
      relation_label: '签署协议',
      tail: '华为',
      tail_canonical: '华为',
      tail_type: 'ORG',
      confidence: 1,
      trigger: '人工校正',
      evidence: '星河科技与华为签署协议。',
      rule_base: 'manual',
    },
  ],
}

const META = { title: '校正测试', recordId: null }

describe('buildCsv', () => {
  it('包含 rule_base 列和人工校正来源', () => {
    const csv = buildCsv(RESULT, META).content
    expect(csv).toContain('rule_base')
    expect(csv).toContain('manual')
    expect(csv).toContain('星河科技')
  })
})

describe('buildMarkdown', () => {
  it('关系表包含来源列并翻译 manual', () => {
    const md = buildMarkdown(RESULT, META).content
    expect(md).toContain('| 头实体 | 关系 | 尾实体 | 断言性质 | 触发词 | 置信度 | 来源 |')
    expect(md).toContain('人工校正')
  })

  it('非事实断言在 Markdown 里被标出来', () => {
    const withRumor = {
      ...RESULT,
      relations: [
        ...RESULT.relations,
        {
          head: '腾讯', relation: 'acquire', relation_label: '收购', tail: '搜狗',
          confidence: 0.57, trigger: '收购', evidence: '有媒体报道称腾讯将收购搜狗。',
          rule_base: 'trigger', assertion: 'rumored', assertion_label: '传闻 / 转述',
          assertion_cue: '媒体报道称',
        },
      ],
    }
    const md = buildMarkdown(withRumor, META).content
    expect(md).toContain('**传闻 / 转述**')
    expect(md).toContain('不是事实陈述')
  })

  it('CSV 带 assertion 列', () => {
    const csv = buildCsv(RESULT, META).content
    expect(csv).toContain('assertion')
    expect(csv).toContain('事实陈述')
  })
})
