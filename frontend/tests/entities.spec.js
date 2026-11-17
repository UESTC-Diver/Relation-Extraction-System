import { describe, expect, it } from 'vitest'
import {
  canonicalize,
  findOccurrences,
  hasSentenceIndex,
  normalizeSentenceIndex,
  sentenceIndexAt,
  syncEntities,
} from '../src/utils/entities'

const ENTITY_TYPES = [
  { key: 'ORG', label: '组织机构', color: '#0ea5e9' },
  { key: 'PERSON', label: '人物', color: '#6366f1' },
]

describe('canonicalize', () => {
  it('递归剥离机构后缀', () => {
    expect(canonicalize('腾讯控股有限公司', 'ORG')).toBe('腾讯')
    expect(canonicalize('阿里巴巴集团', 'ORG')).toBe('阿里巴巴')
  })

  it('非机构与过短名称保持不变', () => {
    expect(canonicalize('北京', 'LOC')).toBe('北京')
    expect(canonicalize('公司', 'ORG')).toBe('公司')
  })
})

describe('findOccurrences / sentenceIndexAt', () => {
  it('找出所有不重叠出现位置', () => {
    expect(findOccurrences('星河科技与华为签约，星河科技总部在北京。', '星河科技')).toEqual([
      [0, 4],
      [10, 14],
    ])
  })

  it('按句子偏移定位', () => {
    const sentences = [
      { index: 0, start: 0, end: 5 },
      { index: 1, start: 5, end: 12 },
    ]
    expect(sentenceIndexAt(sentences, 0)).toBe(0)
    expect(sentenceIndexAt(sentences, 5)).toBe(1)
    expect(sentenceIndexAt(sentences, 99)).toBe(-1)
    expect(sentenceIndexAt([], 0)).toBe(-1)
  })
})

describe('证据句索引', () => {
  it('0 是合法句子，-1/null/缺失都视为未指定', () => {
    expect(hasSentenceIndex({ sentence_index: 0 })).toBe(true)
    expect(hasSentenceIndex({ sentence_index: 2 })).toBe(true)
    expect(hasSentenceIndex({ sentence_index: -1 })).toBe(false)
    expect(hasSentenceIndex({ sentence_index: null })).toBe(false)
    expect(hasSentenceIndex({})).toBe(false)
  })

  it('人工新增时把未指定归一为 -1', () => {
    expect(normalizeSentenceIndex(0)).toBe(0)
    expect(normalizeSentenceIndex(3)).toBe(3)
    expect(normalizeSentenceIndex(-1)).toBe(-1)
    expect(normalizeSentenceIndex(null)).toBe(-1)
    expect(normalizeSentenceIndex(undefined)).toBe(-1)
    expect(normalizeSentenceIndex('2')).toBe(-1)
  })
})

describe('syncEntities', () => {
  it('补上关系里出现但实体清单没有的实体并重算统计', () => {
    const result = syncEntities({
      text: '星河科技与华为签署协议。',
      entities: [
        { id: 'e1', text: '华为', canonical: '华为', type: 'ORG', start: 5, end: 7, source: 'gazetteer' },
      ],
      sentences: [{ index: 0, start: 0, end: 12, text: '星河科技与华为签署协议。' }],
      relations: [
        {
          head: '星河科技',
          head_type: 'ORG',
          head_canonical: '星河科技',
          tail: '华为',
          tail_type: 'ORG',
          tail_canonical: '华为',
        },
      ],
      entityTypes: ENTITY_TYPES,
      now: 7,
    })

    expect(result.entities.map((e) => e.text)).toEqual(['星河科技', '华为'])
    const manual = result.entities[0]
    expect(manual.source).toBe('manual')
    expect(manual.start).toBe(0)
    expect(manual.end).toBe(4)
    expect(manual.sentence_index).toBe(0)
    expect(result.entityCount).toBe(2)
    expect(result.uniqueEntityCount).toBe(2)
    expect(result.entityTypeCounts).toEqual({ ORG: 2, PERSON: 0 })
  })

  it('同一实体在原文出现多次时逐个补入', () => {
    const result = syncEntities({
      text: '星河科技与华为签约，星河科技总部在北京。',
      relations: [
        {
          head: '星河科技',
          head_type: 'ORG',
          head_canonical: '星河科技',
          tail: '华为',
          tail_type: 'ORG',
          tail_canonical: '华为',
        },
      ],
      entityTypes: ENTITY_TYPES,
      now: 1,
    })

    expect(result.entities.filter((e) => e.text === '星河科技')).toHaveLength(2)
    expect(result.entities.filter((e) => e.text === '华为')).toHaveLength(1)
  })

  it('实体文本不在原文时不添加', () => {
    const result = syncEntities({
      text: '华为签署协议。',
      relations: [
        {
          head: '云舟资本',
          head_type: 'ORG',
          head_canonical: '云舟资本',
          tail: '华为',
          tail_type: 'ORG',
          tail_canonical: '华为',
        },
      ],
      entityTypes: ENTITY_TYPES,
    })

    expect(result.entities.some((e) => e.text === '云舟资本')).toBe(false)
    expect(result.entities.some((e) => e.text === '华为')).toBe(true)
  })

  it('已有同一规范实体时不重复添加', () => {
    const result = syncEntities({
      text: '腾讯控股收购搜狗。',
      entities: [
        { id: 'e1', text: '腾讯控股', canonical: '腾讯', type: 'ORG', start: 0, end: 4, source: 'gazetteer' },
        { id: 'e2', text: '搜狗', canonical: '搜狗', type: 'ORG', start: 6, end: 8, source: 'gazetteer' },
      ],
      relations: [
        {
          head: '腾讯',
          head_type: 'ORG',
          head_canonical: '腾讯',
          tail: '搜狗',
          tail_type: 'ORG',
          tail_canonical: '搜狗',
        },
      ],
      entityTypes: ENTITY_TYPES,
    })

    expect(result.entityCount).toBe(2)
    expect(result.entities.every((e) => e.source !== 'manual')).toBe(true)
  })

  it('不与已有实体跨度重叠', () => {
    const result = syncEntities({
      text: '腾讯收购搜狗。',
      entities: [
        { id: 'e1', text: '腾讯', canonical: '腾讯', type: 'PERSON', start: 0, end: 2, source: 'pos' },
      ],
      relations: [
        {
          head: '腾讯',
          head_type: 'ORG',
          head_canonical: '腾讯',
          tail: '搜狗',
          tail_type: 'ORG',
          tail_canonical: '搜狗',
        },
      ],
      entityTypes: ENTITY_TYPES,
    })

    expect(result.entities.some((e) => e.text === '腾讯' && e.type === 'ORG')).toBe(false)
    expect(result.entities.some((e) => e.text === '搜狗' && e.source === 'manual')).toBe(true)
    expect(result.entityTypeCounts).toEqual({ ORG: 1, PERSON: 1 })
  })
})
