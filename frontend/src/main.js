import { createApp } from 'vue'

import App from './App.vue'
import './styles.css'

const app = createApp(App)

/**
 * 站点分流：/ 落地页、/demo 静态试用沙箱都不用 Element Plus，
 * 只有 /app 工作台需要。把整套组件注册放进动态 chunk，首页与试用页
 * 就不必为一个用不到的 UI 库付 600 KB 的下载成本。入口之间是整页
 * 跳转（<a href>），所以每次加载都能按 pathname 正确判断。
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
