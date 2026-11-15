import { createApp } from 'vue'

import App from './App.vue'
import './styles.css'

const app = createApp(App)

/**
 * 站点分流：/ 是纯静态落地页，一个 Element Plus 组件都不用；
 * /app 才是工作台。把整套组件注册放进动态 chunk，首页就不必为一个
 * 用不到的 UI 库付 600 KB 的下载成本。两个入口之间是整页跳转（<a href>），
 * 所以每次加载都能按 pathname 正确判断。
 */
function needsElementPlus() {
  const p = location.pathname.replace(/\/+$/, '') || '/'
  if (p === '/app' || p.startsWith('/app/')) return true
  // 兼容旧链接 /#triples 这类直达工作台页签的锚点
  return (p === '/' || p === '/index.html') &&
    /^#(entities|triples|graph|stats)$/.test(location.hash)
}

if (needsElementPlus()) {
  import('./element-setup').then(({ registerElementPlus }) => {
    registerElementPlus(app)
    app.mount('#app')
  })
} else {
  app.mount('#app')
}
