# stylekit-skill

**简体中文** · [English](README.en.md)

> 给 AI agent 用的前端风格 Skill —— 让生成的 UI 套用一个**具体的、命名的**视觉风格，而不是「AI 默认长相」。

[![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)

这是 [StyleKit](https://github.com/AnxForever/stylekit) 的 Agent Skill。它读取风格目录、实现规格和公开资产目录，再结合目标项目生成或调整界面。Skill 可以直接读取公开 API，也可以复用 StyleKit CLI 或 MCP 返回的规格文件。

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
- **改样式 / 修现有 UI**（「太丑了」「想要 Stripe 那种感觉」）→ 只改违反该风格 tokens 与规则的部分，**保留原有结构和状态**
- **风格迁移** → 取两份规格，对比 tokens 和禁用清单，逐个 class 改。**绝不混用两种风格的 tokens**
- **审查 / 审计一致性** → 取风格规格，把每个组件对着 doList / dontList 和 token 表核一遍，报告要具体到文件和元素

---

## 脚本

| 脚本 | 做什么 |
| --- | --- |
| `detect-project.py` | 检测目标项目的前端上下文，让生成的 UI 贴合项目实际技术栈 |
| `fetch-style.py` | 从公开 API 拉取风格规格，输出面向代码生成的紧凑参考 |
| `fetch-asset.py` | 搜索公开资产目录，读取一项精确资产；可按明确指令物化模板文件或下载 ZIP |
| `verify-spec.py` | 校验 API 规格的内部一致性——**数据自相矛盾时，agent 就会编造 tokens、违反风格规则** |
| `eval-check.py` | **验收检测器**：喂给它代码 + 风格 slug，逐条报告规则违规（禁用 class、缺失项） |
| `benchmark.py` | 合成模板回归测试，或使用 `--llm` 运行真实模型对照实验 |

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

可以直接从 API 读取，也可把已有规格保存下来供生成和验收共用：

```bash
python3 <skill-root>/scripts/fetch-style.py neo-brutalist --json > /tmp/stylekit-spec.json
python3 <skill-root>/scripts/eval-check.py neo-brutalist ./button.tsx --spec /tmp/stylekit-spec.json --component button --strict
```

`--spec` 接收 CLI/API 导出的 JSON 规格；`--from-file` 接收 MCP 工具结果 JSON（优先读取 `structuredContent`，其次读取包含完整 JSON 的 text block）。`_stylekitSource.degraded` 会说明规格是否退回旧格式。测试本机 StyleKit API 时可传 `--base-url http://127.0.0.1:3189/api/styles`。

## 参考文档

- `references/design-principles.md` —— 迭代模式与设计原则
- `references/assets.md` —— 公开资产搜索、许可、模板导入与验收
- `references/style-signatures.md` —— 各风格的辨识特征

---

## 安装

```bash
npx skills add AnxForever/stylekit-skill
```

这只安装 Agent Skill，不会安装或配置 MCP server。若想让客户端通过 MCP 调用 StyleKit，可单独把下面的 stdio server 项加入该客户端的 MCP 配置：

```json
{
  "mcpServers": {
    "stylekit": {
      "command": "npx",
      "args": ["-y", "stylekit-mcp@0.3.0"]
    }
  }
}
```

这是独立的可选接入方式。Skill 不会自动执行 `npx`，也不会改写客户端配置。StyleKit MCP `0.3.0` 提供只读的目录搜索、实现 brief、风格信息、tokens、组件配方、shadcn 安装命令和规则检查工具。

## 相关项目

| 项目 | 是什么 |
| --- | --- |
| [stylekit](https://github.com/AnxForever/stylekit) | 风格库本体 · [stylekit.top](https://stylekit.top) |
| [stylekit-mcp](https://github.com/AnxForever/stylekit-mcp) | MCP Server —— 在 Claude Code / Cursor 里直接调用 |
| **stylekit-skill** | 本仓库：Agent Skill |

## 许可

MIT —— 见 [LICENSE](LICENSE)
