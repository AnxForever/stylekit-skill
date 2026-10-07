# stylekit-skill

**简体中文** · [English](README.en.md)

> 给 AI agent 用的前端风格 Skill —— 让生成的 UI 套用一个**具体的、命名的**视觉风格，而不是「AI 默认长相」。

[![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)

这是 [StyleKit](https://github.com/AnxForever/stylekit) 的 Agent Skill。它读取风格目录、实现规格和公开资产目录，再结合目标项目生成或调整界面。Skill 可以直接读取公开 API，也可以复用已保存的完整 API 规格、CLI brief 或 MCP brief。

---

## 为什么需要它

单靠「做得好看点」很难说清希望界面长什么样。

StyleKit 提供有名称的视觉方向、tokens、组件配方和风格规则，给生成过程一个可查看、可检查的起点。结果仍要结合产品需求和实际页面来判断。

---

## 工作流

```
了解项目 → 选定风格 → 读取规格 → 按项目需要实现 → 检查结果
```

| 步骤 | 做什么 |
| --- | --- |
| **1. 检测上下文** | 查看目标项目的框架、Tailwind 和现有组件 |
| **2. 选风格** | 把用户的意图匹配到目录里的某个 slug |
| **3. 读规格** | 获取当前可用的风格说明、tokens、配方和检查规则 |
| **4. 实现与检查** | 让风格特征服务于产品，再检查代码和实际页面 |

## 任务分流

按用户实际要的东西走不同路径：

- **新建 UI**（页面、组件、看板、落地页）→ 走完整工作流
- **改样式 / 修现有 UI**（「太丑了」「想要 Stripe 那种感觉」）→ 调整相关视觉细节，保留原有行为、数据和路由；结构变化以实际需求为准
- **风格迁移** → 对比两份规格，把相关视觉选择映射到项目已有的语义 tokens，保留用户明确要求的品牌与交互
- **审查 / 审计一致性** → 取风格规格，把每个组件对着 doList / dontList 和 token 表核一遍，报告要具体到文件和元素
- **移动端设计 / 组件选型** → 先确认 Web、React Native / Expo、SwiftUI 或 Flutter，再选择当前项目可用的实现

## 移动端与开源组件

技能会区分手机网页和原生应用：ChunUI、ShipSwift 用于 SwiftUI；Ant Design Mobile 和 Radix Dialog 面向 React Web；Vant 面向 Vue；React Native Paper、Bottom Sheet 面向 RN。对于「Next.js 页面想要 ChunUI 那种质感」，应在现有 Web 技术栈中实现视觉适配，不会把 SwiftUI 当成 npm 组件安装。

新增 [移动端指导](references/mobile-ui.md) 覆盖组件选择、底部导航和弹层、触控、安全区、键盘遮挡与主题刷新。推荐附官方来源，并要求核对兼容性和许可；这些是外部组件资料，不保证出现在 StyleKit 公开资产目录中。

例如可以直接要求：

- 「优化这个 Next.js 商品页的移动端，保留现有购物车逻辑，参考 ChunUI 的灰阶和按钮层次。」
- 「这是 Expo 项目，先比较合适的底部面板组件，暂时不要安装依赖。」
- 「检查这个 SwiftUI 界面能否采用 ChunUI，说明系统版本和工具链要求。」

---

## 脚本

| 脚本 | 做什么 |
| --- | --- |
| `detect-project.py` | 识别 Web / Expo / React Native / SwiftUI / Flutter 的代码与依赖证据，列出多项目路径和已声明的组件库 |
| `fetch-style.py` | 从公开 API 拉取风格规格，输出面向代码生成的紧凑参考 |
| `fetch-asset.py` | 搜索公开资产目录，读取一项精确资产；可按明确指令物化模板文件或下载 ZIP |
| `verify-spec.py` | 校验 API 规格的内部一致性——**数据自相矛盾时，agent 就会编造 tokens、违反风格规则** |
| `eval-check.py` | **验收检测器**：喂给它代码 + 风格 slug，逐条报告规则违规（禁用 class、缺失项） |
| `benchmark.py` | 合成模板回归测试，或使用 `--llm` 运行真实模型对照实验 |
| `update-skill.py` | 按发布清单检查更新；遇到本地改动或文件冲突时跳过 |

`eval-check.py` 只检查静态可读的 class 规则。默认 benchmark 使用四个固定模板任务检查 evaluator 和样例数据，不能说明真实模型生成质量；`--llm` 才会调用 OpenAI 兼容接口进行小规模对照。要观察 Agent 是否实际采用 Skill，可在独立消费项目中做一次手工 forward test；[流程与证据边界见此](references/forward-test.md)。

## 公开资产目录

风格规格和站点资产是两类数据。资产脚本通过 StyleKit 的 `/api/assets` 目录搜索公开条目，种类由目录结果提供；可搜索动画、背景、渐变、阴影、字体、组件模式、Prompt、模板和体验包等资产。它显示 `availability`、`contentLevel`、来源、许可和依赖，不会把搜索结果误当作可复制源代码。

```bash
python3 <skill-root>/scripts/fetch-asset.py search "grain texture" --kind background
python3 <skill-root>/scripts/fetch-asset.py get background ASSET_ID --json > /tmp/stylekit-asset.json
python3 <skill-root>/scripts/fetch-asset.py get template editorial-blog --output-dir ./stylekit-editorial-blog
python3 <skill-root>/scripts/fetch-asset.py get template editorial-blog --download-to /tmp/editorial-blog.zip
```

用搜索结果里的确切 `kind/id` 替换示例 ID。模板源文件只写入新的目标目录；模板 ZIP 需要显式指定保存路径。两个动作都不会解压 ZIP、安装依赖或修改应用配置。受限资产只显示元数据，外部资产不会自动跟随来源。详细流程、许可判断和失败边界见 [references/assets.md](references/assets.md)。`--spec` 支持已保存 API JSON；`--from-file` 支持符合契约的 MCP 结构化结果或完整 JSON 文本块。本机测试接口可通过 `--base-url http://127.0.0.1:3189/api/assets` 指定。

## 规格文件与脚本

脚本需要 Python 3.10 或更新版本。安装后，脚本位于 Skill 自己的 `scripts/` 目录；从目标项目运行时，应使用安装目录下的脚本路径，不能假设目标项目也有 `scripts/`。

可以直接从 API 读取，也可把已有规格保存下来供生成和验收共用。以下占位路径需要替换为真实路径；为每次任务创建单独的工作目录：

```bash
python3 "<skill-root>/scripts/fetch-style.py" neo-brutalist --json > "<work-dir>/spec.json"
python3 "<skill-root>/scripts/eval-check.py" neo-brutalist ./button.tsx --spec "<work-dir>/spec.json" --component button --strict
```

`--spec` 接收完整 `stylekit-brief-v1`（包括 `stylekit-cli brief` 的输出）或受支持的旧版 API 规格；CLI 的详情摘要或 tokens 输出不能替代完整规格。`--from-file` 接收 MCP 工具结果 JSON（优先读取 `structuredContent`，其次读取包含完整 JSON 的 text block）。`_stylekitSource.degraded` 会说明规格是否退回旧格式。测试本机 StyleKit API 时可传 `--base-url http://127.0.0.1:3189/api/styles`。确切的 npm 包名、已验证版本和命令见 [规格来源与检查](references/spec-workflow.md)。

项目检测保留原有 Web 字段，新增 `platforms`、`componentLibraries` 和按相对路径列出的 `projects`。后者是清单和源码识别出的候选项目，可能包含共享包或声明了框架开发依赖的 workspace 根目录，不证明它有可运行的应用入口。混合仓库的顶层平台和组件库是检测结果的合并；`framework` 仍描述所选目录自身。请在真正要改的应用子目录再次检测。SwiftUI 导入不代表一定是 iOS，检测到的依赖声明也不代表已安装或版本兼容。静态 class 检查器只适用于对应的 Web 规则，不能验证原生界面。

## 参考文档

- `references/design-principles.md` —— 迭代模式与设计原则
- `references/assets.md` —— 公开资产搜索、许可、模板导入与验收
- `references/style-signatures.md` —— 各风格的辨识特征
- `references/mobile-ui.md` —— 移动端模式、ChunUI 等组件的适用边界与验收
- `references/spec-workflow.md` —— CLI / API / MCP 规格复用与静态检查边界
- `references/updates.md` —— 固定版本、更新开关与本地修改保护

---

## 安装

```bash
npx skills@latest add AnxForever/stylekit-skill
```

这只安装 Agent Skill，不会安装或配置 MCP server。首次安装后的 Skill 会在每次启用时按 24 小时缓存检查 GitHub `main`；发现更新后先重读新的 `SKILL.md`。离线时继续使用当前版本，检测到本地改动会跳过整次更新。客户端仍需遵循 Skill 的启动指令，不能由仓库强制执行。若安装来源显式固定到 tag 或 commit，请先禁用自动更新；本机制不会检测安装器的 pin，默认跟随 `main`。

已从本仓库安装的旧版，可通过 Skills CLI 升级一次以接入此机制。项目级安装在项目目录运行 `npx skills@latest update stylekit --project`；全局安装运行 `npx skills@latest update stylekit --global`。省略范围参数会同时考虑项目和全局的同名安装。Skills CLI 会沿用安装记录中的来源，不会把其他仓库的旧安装自动迁到本仓库；这种情况应先核对来源，再按上面的安装命令重新选择目标。Skills CLI 可能替换现有 Skill 目录；如果你改过里面的文件，请先另存。后续可用以下命令查看或控制自动检查：

```bash
python3 <skill-root>/scripts/update-skill.py --status
python3 <skill-root>/scripts/update-skill.py --disable
python3 <skill-root>/scripts/update-skill.py --enable
python3 <skill-root>/scripts/update-skill.py --force-check
```

强制检查只跳过 24 小时等待，不会覆盖本地改动；禁用时，自动检查和强制检查都会停止，直到再次启用。

若想让客户端通过 MCP 调用 StyleKit，可单独把下面的 stdio server 项加入该客户端的 MCP 配置：

```json
{
  "mcpServers": {
    "stylekit": {
      "command": "npx",
      "args": ["-y", "--prefer-online", "stylekit-mcp@latest"]
    }
  }
}
```

这是独立的可选接入方式。Skill 不会改写客户端配置。当前 StyleKit MCP 提供风格与实现 brief、公开资产目录搜索和单项详情等只读工具；以[官方包文档](https://github.com/AnxForever/stylekit/tree/main/packages/mcp)和连接后的工具清单为准。`@latest` 会在客户端重新启动 MCP 进程时检查 npm 上的当前版本；已经运行的进程需要重启后才会使用新版本。

## 相关项目

| 项目 | 是什么 |
| --- | --- |
| [stylekit](https://github.com/AnxForever/stylekit) | 风格库本体 · [stylekit.top](https://stylekit.top) |
| [stylekit-mcp](https://github.com/AnxForever/stylekit-mcp) | MCP Server —— 在 Claude Code / Cursor 里直接调用 |
| **stylekit-skill** | 本仓库：Agent Skill |

## 发布维护

修改 `SKILL.md`、`scripts/`、`references/`、`agents/` 或 `assets/` 后，递增 `scripts/generate-release-manifest.py` 中的 `RELEASE_VERSION`，再运行 `python3 scripts/generate-release-manifest.py`。CI 会校验文件哈希，并要求受管理内容变化时版本递增。清单不包含自身或本地更新状态。

## 许可

MIT —— 见 [LICENSE](LICENSE)
