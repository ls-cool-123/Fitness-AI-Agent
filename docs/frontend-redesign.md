# 前端重构方向调研（2026-10）

目标：把现在的「功能正确但偏朴素」的界面，做成有动效、有反馈、能留住人的产品级界面。
约束：React 19 + Vite + Tailwind 4 + Radix（目前只用了 Tabs）+ Recharts，不引入重型 3D 依赖。

---

## 〇、当前进度（2026-10 更新）

| 能力 | 状态 |
|---|---|
| 工具结果卡片（训练表 / 进展 / 分类 / 记忆 / 参考资料） | ✅ 已有 |
| HITL 确认卡片（可编辑 + 确认/取消 + 409 终态） | ✅ 已有，但无动效 |
| 流式 NDJSON 逐字渲染 | ✅ 已有 |
| 训练看板（KPI / 趋势 / 分类） | ✅ 已有，静态呈现 |
| 动效基建（Motion） | ❌ 未做 |
| 列表增删过渡（AutoAnimate） | ❌ 未做 |
| Toast / Dialog 原语 | ❌ 未做 |
| 回答内 `[1][2]` 引用角标 | ❌ 未做（`rag_search_tool` 已返回 `index`，具备实现条件） |

---

## 一、现状判断

| 维度 | 现状 | 问题 |
|------|------|------|
| 组件层 | 自建 `components/ui/*`（button/card/input/delta/tabs） | 缺 dialog / toast / tooltip / skeleton / select，后面做交互会反复手搓 |
| 动效 | 基本没有，只有 CSS 过渡 | 列表增删、卡片展开、数字变化都是硬切 |
| 图表 | Recharts | 首屏直接出结果，没有入场与交互反馈 |
| 打包体积 | 691 kB / gzip 207 kB | 已经偏大，再加三个动画库会失控 |

结论：**先补「动效基建 + 少量高杠杆组件」，不要整套换 UI 库**。

---

## 二、值得引入的（按性价比排序）

### 1. Motion（原 Framer Motion）—— 动效基建

- 包名 `motion`，从 `motion/react` 导入；约 35 kB gzip，是下面所有组件的共同底座。
- 用在哪：消息入场 stagger、工具卡片高度展开（`AnimatePresence` + `layout`）、确认卡片出现、Tab 下划线滑动（`layoutId`）。
- 必做：`useReducedMotion()`，系统开了「减少动态效果」就退化为无动画。

```bash
npm i motion
```

### 2. Magic UI —— 直接抄组件，不要装包

- 官网 <https://magicui.design>，GitHub ~15k star，copy-paste 模式，单组件通常 < 5 kB。
- 与健身项目最搭的几个：
  - **NumberTicker**：KPI 数字滚动（总训练量、深蹲 PR），比静态数字有生命力；
  - **AnimatedBeam**：把「Agent → 4 个工具 → MySQL/Qdrant」画成流动的连接线，适合放架构说明或空状态页；
  - **BorderBeam / ShimmerButton**：主 CTA 与「待确认」卡片的高亮边框；
  - **Marquee**：动作库或成就徽章的横向滚动。
- 注意：它的默认配色偏深色开发者风格，落到本项目要用现有 CSS 变量（`--brand`、`--hairline`、`--delta-up`）替换硬编码颜色。

### 3. Motion Primitives —— 文字与微交互

- <https://motion-primitives.com>，同样 copy-paste，基于 Motion。
- 适合：流式回答的逐字渐显（`TextEffect`）、工具调用中的 shimmer 占位、图片/卡片 hover 倾斜。
- 比 Aceternity 轻，适合应用内界面；Aceternity 更适合营销落地页。

### 4. AutoAnimate —— 一行代码的列表动画

```tsx
import { useAutoAnimate } from "@formkit/auto-animate/react";
const [parent] = useAutoAnimate();
<div ref={parent}>…messages…</div>
```

- 消息列表、训练记录表格、来源卡片列表的增删自带过渡，改动成本几乎为零。

### 5. shadcn/ui —— 补齐缺失的原语（可选用 CLI 按需拉）

- 只装真正需要的：`dialog`、`sonner`（toast）、`tooltip`、`skeleton`、`select`、`scroll-area`。
- 已确认兼容 Tailwind v4（官方提供 v4 迁移指引）。
- 好处：Dialog/Toast 的无障碍与焦点管理不用自己写，后面做「确认写入」「记录成功」提示会省很多事。

### 6. 21st MCP / CLI —— 让 Agent 直接产出组件

- <https://21st.dev/mcp>（原名 Magic MCP，`@21st-dev/magic` 仍可用别名），12000+ 社区组件，支持 Cursor / Claude Code 等 MCP 客户端。
- 用法：`npx @21st-dev/cli@latest init --client claude`，之后可以直接让 Agent「生成一个训练量环形进度卡」并落进 `components/`。
- 免费额度：每天 2 次组件代码获取；找灵感/搜索不消耗。
- 另有 agent skills 清单：`https://21st.dev/.well-known/skills/index.json`。

### 7. 可参考但先别做

| 方案 | 为什么先别做 |
|------|-------------|
| Aceternity UI（3D 卡片、粒子背景） | 部分组件依赖 Three.js（~600 kB），落在应用主包里不划算；只适合独立落地页 |
| assistant-ui | 聊天原语很强，但本项目是自建 NDJSON 协议 + 工具卡片，接入等于重写流层，收益不确定 |
| GSAP / react-spring | 与 Motion 能力重叠，两套动画系统会让代码风格分裂 |

---

## 三、本项目可落地的 6 个具体改造

1. **对话流**：消息 `stagger` 入场 + 流式文字渐显；工具卡片用 `layout` 动画从骨架展开为结果；待确认卡片加 `BorderBeam` 呼吸边框，`确认/取消` 时整卡收起并显示结果徽标。
2. **看板 KPI**：`NumberTicker` 滚动数字 + 环比 `delta` 箭头位移；无数据时用骨架屏而不是 `--`。
3. **趋势图**：Recharts 的 `Line` 用 `strokeDasharray` 做绘制动画，柱状图初值 0 生长；hover 时显示十字准星与 tooltip 联动。
4. **Tab 切换**：`layoutId` 下划线在「对话 / 看板 / 知识库」之间滑动，而不是直接换色。
5. **反馈层**：接入 `sonner`，记录成功/失败用 toast 而非页面内文字；危险操作（删除文档）用 `dialog` 二次确认。
6. **空状态**：用 AnimatedBeam 画一张「你和 AI 教练的数据流」小图，替代干巴巴的「暂无数据」。

性能红线：
- 新增依赖控制在 Motion + AutoAnimate + sonner 以内（合计 ~45 kB gzip）；
- 图表与看板路由级懒加载；
- 所有动画走 `transform` / `opacity`，不用 top/left/width 做逐帧动画。

---

## 四、设计方向建议

保持现在的深色 + 品牌色体系，往「数据感」走而不是「炫技感」：

- **层级**：页面底色 → 卡片 → 悬浮元素三级明度差，用 1px `--hairline` 分隔而不是重阴影；
- **强调色克制**：只有 CTA、PR、待确认三处用品牌色，其余用中性色 + 数值本身做视觉重心；
- **动效时长**：入场 200–300ms，展开 250ms，hover 120ms；统一走一套 easing；
- **密度**：训练数据表格允许紧凑，但 KPI 卡要留白。

---

## 五、参考链接

- Motion 组件与 Magic UI 对比（2026）：<https://www.pkgpulse.com/guides/aceternity-ui-vs-magic-ui-vs-shadcn-animated-react-2026>
- 21st 组件库与 MCP：<https://21st.dev/llms.txt>
- assistant-ui（评估用）：<https://www.assistant-ui.com/docs/primitives>
