import { ref } from 'vue'
import {
  ElButton,
  ElCheckbox,
  ElCollapse,
  ElCollapseItem,
  ElDialog,
  ElDrawer,
  ElDropdown,
  ElDropdownItem,
  ElDropdownMenu,
  ElEmpty,
  ElForm,
  ElFormItem,
  ElIcon,
  ElInput,
  ElOption,
  ElPagination,
  ElPopconfirm,
  ElProgress,
  ElRadioButton,
  ElRadioGroup,
  ElScrollbar,
  ElSelect,
  ElTable,
  ElTableColumn,
  ElUpload,
  ElLoadingDirective,
  localeContextKey,
} from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import 'element-plus/dist/index.css'
// 覆盖必须排在组件库 CSS 之后：把 primary 从默认蓝改回纸墨朱的朱红
import './element-overrides.css'

// 按需注册：全量 app.use(ElementPlus) 会把所有组件塞进这个 chunk。
// 图标同理，各组件在 <script setup> 里局部 import 自己要用的。
// 中文文案通过 localeContextKey 注入，避免按需注册后分页器等默认变英文。
const components = {
  ElButton, ElCheckbox, ElCollapse, ElCollapseItem,
  ElDialog, ElDrawer, ElDropdown, ElDropdownItem, ElDropdownMenu,
  ElEmpty, ElForm, ElFormItem, ElIcon, ElInput, ElOption,
  ElPagination, ElPopconfirm, ElProgress, ElRadioButton, ElRadioGroup,
  ElScrollbar, ElSelect, ElTable, ElTableColumn, ElUpload,
}

export function registerElementPlus(app) {
  for (const [name, component] of Object.entries(components)) {
    app.component(name, component)
  }
  app.directive('loading', ElLoadingDirective)
  app.provide(localeContextKey, ref(zhCn))
}
