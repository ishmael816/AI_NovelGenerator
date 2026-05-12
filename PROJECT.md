# NoverGen — AI 网文全流程生成系统

番茄小说（Tomato Novel）平台的 AI 辅助创作工具，覆盖从选题、大纲、章节生成到审阅、精修的完整流水线。

## 核心流水线

```
选题策划 → 大纲生成 → 架构设计 → 蓝图拆分 → 逐章生成 → 最终化 → 阅读审阅 → 划线改写
```

| 阶段 | 模块 | 输出 |
|------|------|------|
| 批量选题 | `batch_outline_generator.py` | 10 个主流题材大纲 JSON |
| 大纲审阅 | `outline_reviewer/` Web UI | 标注、编辑、入队 |
| 架构生成 | `architecture.py` | `Novel_architecture.txt` |
| 蓝图拆分 | `blueprint.py` | `Novel_directory.txt` |
| 逐章生成 | `chapter.py` | `chapter_N.txt` + `outline_N.txt` |
| 最终化 | `finalization.py` | 字数修正、状态更新、向量入库 |
| 阅读审阅 | `reader.html` | 章节阅读、钩子分析、蓝图对照 |
| 划线改写 | `rewrite_agent.py` + reader UI | 选中文本 → LLM 改写 → Diff 对比 → 行内编辑 → 数据飞轮 |

## 项目结构

```
AI_NovelGenerator/
├── novel_generator/           # 核心生成引擎
│   ├── architecture.py        # 世界观 + 人物体系 + 剧情架构
│   ├── blueprint.py           # 逐章蓝图（分块增量生成）
│   ├── chapter.py             # 多阶段章节 Draft（含向量检索上下文）
│   ├── finalization.py        # 后处理：字数控制 + 状态更新 + 向量入库
│   ├── rewrite_agent.py       # 反 AI 味划线改写（上下文窗口 + 风格预设）
│   ├── hook_engine.py         # 钩子检测 + 章末悬念生成
│   ├── word_count_control.py  # 番茄平台字数优化（2000-2200 字）
│   ├── title_generator.py     # 书名 + 简介生成
│   ├── vectorstore_utils.py   # ChromaDB 向量库操作
│   ├── knowledge.py           # 知识库导入 + 文档分块
│   ├── common.py              # LLM 调用重试、输出清洗
│   ├── style_presets.json     # 6 种改写风格预设
│   └── prompt_definitions.py  # Prompt 模板集中管理
│
├── outline_reviewer/          # 大纲审阅 + 阅读器 Web 服务
│   ├── server.py              # HTTP Server（Python stdlib 零依赖）
│   └── webui/
│       ├── index.html         # 大纲审阅 UI（标注、编辑、队列）
│       ├── generate.html      # 批量生成队列管理 UI
│       └── reader.html        # 小说阅读器 + 划线改写 UI
│
├── llm_adapters.py            # 多厂商 LLM 适配器（OpenAI / Gemini / Azure / Ollama）
├── embedding_adapters.py      # 多厂商 Embedding 适配器
├── config_manager.py          # 配置加载与校验
├── config.json                # API Key、模型选择、小说参数
├── batch_outline_generator.py # 批量大纲生成（10 个 2026 番茄热门题材）
├── generate_from_queue.py     # 从队列驱动全流程生成
├── consistency_checker.py     # 剧情矛盾检测
├── review_constraints.py      # 将审阅标注转为生成约束
├── ui/                        # CustomTkinter 桌面 GUI
│   ├── main.py                # 入口
│   ├── main_window.py         # 主窗口
│   └── ...
└── output/                    # 生成输出
    ├── outlines/              # 大纲 JSON
    ├── novels/<name>/         # 逐小说
    │   ├── chapters/          # chapter_N.txt
    │   ├── vectors/           # ChromaDB
    │   ├── Novel_architecture.txt
    │   └── Novel_directory.txt
    └── review/                # 审阅数据
        ├── annotations.json   # 标注
        ├── edits.json         # 编辑历史
        ├── queue.json         # 生成队列
        └── rewrite_history.jsonl  # 数据飞轮日志
```

## LLM 与 Embedding 支持

| 接口 | LLM | Embedding |
|------|-----|-----------|
| OpenAI 兼容 | GPT-5, DeepSeek V3, 网易雷火 | ✅ |
| Google | Gemini 2.5 Flash | ✅ |
| Azure | Azure OpenAI | — |
| 本地 | Ollama | ✅ |

配置通过 `config.json` 切换，支持不同任务使用不同模型。

## 阅读器 + 划线改写（reader.html）

阅读器是本系统交互最密集的模块，支持：

### 基础阅读
- 左侧目录树导航 + 章节切换
- 字号调节、滚动位置持久化（localStorage）
- 蓝图面板对照、钩子密度分析、审阅约束参考

### 划线改写工作流
```
划选文本 → 浮动工具条 → 选风格/输入指令 → LLM 改写
    → Diff 弹窗（句级对比）→ 行内编辑 → 应用 → 段落格式保留
```

**6 种风格预设**：去冗余比喻、加重戾气、转大白话、增加微表情、拆长句、Show-Don't-Tell

**Diff 弹窗特性**：
- 句级 Diff（按 `。！？…` 拆句，变更以句子为单位高亮）
- 左右双栏同步滚动
- 右侧 `contentEditable` 行内编辑
- 撤销按钮（恢复原文并 PUT 回 server）

**键盘快捷键**：`Ctrl+Enter` 触发改写（编辑指令输入框中亦可用）

**工具条定位**：`position: fixed` 跟随选中文字下方

### 数据飞轮

每次应用改写时，静默记录到 `output/review/rewrite_history.jsonl`：

```json
{
  "timestamp": "2026-05-12T...",
  "novel_name": "重生逆袭",
  "chapter_num": 3,
  "original_text": "他感到一阵寒意袭来...",
  "instruction": "加重戾气",
  "ai_rewritten": "冷气钻进骨头缝里...",
  "user_edited": "冷气钻进骨头缝。他咬紧牙关。"
}
```

积累 100+ 条后可作为 Few-shot 语料库微调小模型，让系统逐步学习个人文风。

## 质量模块

| 模块 | 功能 |
|------|------|
| **字数控制** | 目标 2000-2200 字，硬限 1800-2500，最多 2 轮 LLM 调整 |
| **钩子引擎** | 检测 5 类钩子（信息/冲突/反转/情感/能力），章末悬念生成 |
| **一致性检测** | 检测剧情矛盾（基础版） |
| **风格预设** | 6 种反 AI 味改写规则 |
| **审阅约束** | 将标注和编辑转为章节生成时的 CRITICAL/SUGGESTION 约束 |

## 快速开始

```bash
cd AI_NovelGenerator

# 配置 API Key
cp config.example.json config.json
# 编辑 config.json 填写 API Key 和模型选择

# 安装依赖
pip install -r requirements.txt

# 方式一：桌面 GUI
python -m ui.main

# 方式二：命令行全流程
python generate_from_queue.py

# 方式三：Web 审阅服务
cd outline_reviewer
python server.py --port 8080
# 打开 http://localhost:8080
```

## 技术栈

- **语言**: Python 3.9+
- **LLM 框架**: LangChain + OpenAI SDK + Google GenAI
- **向量库**: ChromaDB 1.0 + sentence-transformers
- **桌面 GUI**: CustomTkinter 5.2
- **Web 服务**: Python stdlib `http.server`（零依赖）
- **前端**: 原生 HTML/CSS/JS，暗色主题，无框架
- **存储**: 本地文件系统（txt + json + jsonl），ChromaDB 持久化

## 设计理念

1. **最小依赖** — Web 服务使用 stdlib，前端无框架，降低部署复杂度
2. **容错恢复** — 每个阶段保存中间产物，支持断点续传
3. **人机协作** — 生成→审阅→改写→再生成循环，AI 助力而非替代
4. **数据积累** — 飞轮机制将人工精修转化为可复用资产
