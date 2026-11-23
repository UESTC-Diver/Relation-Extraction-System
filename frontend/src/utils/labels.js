export const RULE_BASE_LABEL = {
  pattern: '句式模板',
  trigger: '触发词',
  passive: '被动句',
  conjunction: '并列结构',
  postmodifier: '后置定语',
  attributive: '职位线索',
  coref: '指代消解',
  chain: '主语链',
  manual: '人工校正',
}

export function ruleLabel(base) {
  return RULE_BASE_LABEL[base] || base || '—'
}
