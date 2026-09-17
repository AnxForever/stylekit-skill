# stylekit-skill

**简体中文** · [English](README.en.md)

> 给 AI agent 用的前端风格 Skill —— 让生成的 UI 套用一个**具体的、命名的**视觉风格，而不是「AI 默认长相」。

[![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)

这是 [StyleKit](https://github.com/AnxForever/stylekit)（509 Stars）的 Agent Skill 实现。让 AI 直接问风格库要设计 tokens、组件配方和 do / don't 规则，然后**照着规则生成**。

---

## 为什么需要它

让 AI 做一个落地页，你会得到一个能跑、但**和所有 AI 做的落地页长得一样**的东西。

问题不在模型——**「做得好看点」不是一份可执行的规格**。StyleKit 把一个视觉方向变成 agent 真能照着做的东西：一个有名字的风格、一组真实的 tokens、一份硬约束，以及一个可以先看的例子。

---

## 工作流

```
检测项目上下文 → 选定风格 → 拉取完整规格 → 安装主题 → 带着规则生成
```

| 步骤 | 做什么 |
| --- | --- |
| **1. 检测上下文** | 先搞清楚目标项目的技术栈，不靠猜 |
| **2. 选风格** | 把用户的意图匹配到目录里的某个 slug |
| **3. 拉规格** | 取该风格的 tokens、组件配方与 AI 规则 |
| **4. 装主题**（可选） | 把 shadcn registry 主题装进项目 |
| **5. 带规则生成** | 用该风格**确切的** tokens 和 do / don't 清单 |

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
| `verify-spec.py` | 校验 API 规格的内部一致性——**数据自相矛盾时，agent 就会编造 tokens、违反风格规则** |
| `eval-check.py` | **验收检测器**：喂给它代码 + 风格 slug，逐条报告规则违规（禁用 class、缺失项） |
| `benchmark.py` | 有 skill vs 无 skill 的生成质量对比（默认 fixture 模式，CI 安全） |

`eval-check.py` 和 `benchmark.py` 是这套设计的重点：**风格约束不是靠「假设模型写对了」，而是靠检测。** 后者还提供了一组可复现的对照，用来衡量 skill 本身到底有没有用。

## 参考文档

- `references/design-principles.md` —— 迭代模式与设计原则
- `references/style-signatures.md` —— 各风格的辨识特征

---

## 安装

```bash
npx skills add AnxForever/stylekit-skill
```

## 相关项目

| 项目 | 是什么 |
| --- | --- |
| [stylekit](https://github.com/AnxForever/stylekit) | 风格库本体（509 Stars）· [stylekit.top](https://stylekit.top) |
| [stylekit-mcp](https://github.com/AnxForever/stylekit-mcp) | MCP Server —— 在 Claude Code / Cursor 里直接调用 |
| **stylekit-skill** | 本仓库：Agent Skill |

## 许可

MIT —— 见 [LICENSE](LICENSE)
