# 质量保障四模块 — 产品设计文档

> 日期：2026-05-12
> 目标：番茄小说平台优质内容生产，提升留存变现能力

---

## 背景

现有 AI_NovelGenerator 具备完整的生成管线（架构 → 蓝图 → 正文 → 总结），四个 WebUI 模块（生成器/审阅器/阅读器/生成器后台），但存在两个根本问题：

1. **质量保障弱**：一致性检查是手动触发，没有钩子密度/完读率预估/字数控制
2. **模块断层**：审阅器改了内容，正文生成器不知道；阅读器发现问题，无法回流

基于番茄平台规则（首章完读率 >60%，10 万字完读率 >17%，2000-2200 字/章，每 500-1000 字必须一个钩子），本次设计覆盖四个 P0 模块。

---

## P0-1：书名/简介生成器

### 问题

番茄的"吸量"第一关是书名+封面+简介 → 用户点击。AI 直出书名缺乏网文味，没有信息差钩子，导致首秀验证期点击量不达标。

### 设计

**新增 `novel_generator/title_generator.py`**

```
generate_titles(outline_content, style='tomato', count=5)
  → [{title, score, dimensions: {信息密度, 悬念强度, 差异化, 情绪张力}, reason}]

generate_synopsis(outline_content, selected_title)
  → {synopsis, char_count, hook_tags: []}
```

**Prompt 设计要点**：
- 编码番茄标题规律：16-22 字微短剧风长句体
- 公式：身份 + 动作 + 反差 + 情绪钩子
- 热门模板识别：听劝后/重生后/系统给了我/开局xxx
- 避坑规则：文艺腔、抽象名、两字名一律拒绝
- 简介：50 字内，核心设定 + 情感钩子 + 悬念留白

**API 端点**：

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/outlines/{id}/generate-titles` | 生成 5 个候选书名，各带评分 |
| POST | `/api/outlines/{id}/generate-synopsis` | body: `{title}` → 生成配套简介 |

**前端改动**：审阅器大纲详情页 header 区增加"书名优化"按钮 → 弹出面板：
- 5 个候选书名列表，各带 4 维评分条（信息密度/悬念强度/差异化/情绪张力）
- 悬停显示评分理由
- 点选书名 → 生成配套简介
- 接受 → 直接替换大纲"书名字" section（走现有 `PUT /api/outlines/{id}`）

---

## P0-2：钩子强度检测 + 章末钩子生成

### 问题

AI 直出正文最大痛点是平铺直叙。番茄平台要求每 500-1000 字一个微钩子，章末必须卡悬念。没有钩子密度 → 完读率崩盘 → 追更比归零 → 流量断崖。

### 设计

**钩子类型体系**：

| 类型 | 定义 | 示例 |
|------|------|------|
| 信息钩子 | 暗示有重要信息未揭露，但还差一点 | "她看了一眼诊断报告，脸色瞬间变了" |
| 冲突钩子 | 引入对抗或威胁 | "林昼还没说完，办公室门被一脚踹开" |
| 反转钩子 | 颠覆已有认知 | "弹窗第 3 条的真正意思，他三个月后才懂" |
| 情感钩子 | 高张力情感时刻 | "赵一帆删掉了代码。这是他第一次背叛林昼" |
| 能力钩子 | 展示/暗示主角隐藏能力 | "他把手机转向对方——数字让对方瞳孔骤缩" |

**新增 `novel_generator/hook_engine.py`**：

```python
def detect_hooks(chapter_text: str) -> HookReport:
    """LLM low-temp 扫描章节，标记所有钩子位置/类型/强度"""
    return {
        "hooks": [{"position": 156, "type": "信息钩子", "strength": 0.7}, ...],
        "density": 3.2,            # 每千字钩子数
        "distribution": {"前1/3": 3, "中1/3": 2, "后1/3": 1},
        "end_cliffhanger": False,  # 章末是否有 ≥0.8 强度钩子
        "score": 72                # 0-100
    }

def generate_cliffhanger(chapter_content: str, next_blueprint: str) -> list[str]:
    """基于本章内容和下章蓝图，生成 3 个章末钩子候选"""
```

**Prompt 注入**：在 `build_chapter_prompt()` 末尾追加：

```
【硬性钩子要求】
- 每 500-800 字必须包含至少一个微钩子（信息差/冲突暗示/情感张力）
- 章末最后 2-3 段必须是高强度悬念钩子（强度 ≥0.8），让读者必须点下一章
- 禁止平铺直叙。禁止"一切顺利"式的平静结尾。禁止"就这样，xxx"式的叙事结束语
```

**API 端点**：

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/novels/{name}/chapters/{n}/hooks` | 检测已有章节钩子分布 |
| POST | `/api/novels/{name}/chapters/{n}/cliffhanger` | 生成章末钩子备选（3 个） |

**前端改动**：阅读器新增"钩子密度"面板：
- 每 500 字一段的热力条（绿 = 强度 ≥0.7 / 黄 = 0.4-0.7 / 灰 = <0.4）
- 章末钩子单独标记 ✦
- 整本小说的钩子密度趋势曲线
- 趋势下降段落高亮警告

---

## P0-3：审阅器 → 正文生成联动

### 问题

审阅器改了"主角人设"，给"核心设定"打了批注，把几份大纲放进待写清单——但正文生成器仍读原始 `Novel_architecture.txt`。所有审阅工作归零。

### 设计

**新增 `novel_generator/review_constraints.py`**：

```python
class ReviewConstraints:
    replaced_content: dict     # section_key → 编辑后内容（直接替换）
    constraints: list[dict]    # [{section, constraint_text, priority}]

def load_review_constraints(outline_id: str) -> ReviewConstraints:
    """
    1. 读 edits.json → replaced_content
    2. 读 annotations.json → constraints
    3. 按 priority (critical/suggestion) 排序
    """
```

**约束注入 `chapter.py`**：

1. 生成前：`replaced_content` 直接覆盖 architecture 中对应 section
2. 每章 prompt 末尾注入：

```
【审阅约束 - 本章必须遵守】
1. [critical/主角人设] 林昼必须展示情感弱点，不能从头理性到尾
2. [suggestion/核心设定] 系统的代价机制应在本章有所暗示
```

3. 生成后：自动调用 `consistency_checker.check_consistency()`，对比生成内容是否满足约束，不满足的标红

**API 端点**：

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/outlines/{id}/constraints` | 返回审阅约束摘要 |
| POST | `/api/queue/start-novel` | body: `{outline_id, model, chapter_count, words_per_chapter}` |
| GET | `/api/novels/{name}/constraints` | 当前正文使用的约束集 |

**前端改动**：

审阅器：大纲详情页"生成正文"按钮 → 展示约束摘要面板 → 配置参数 → 确认

阅读器：蓝图面板旁增加"约束对照"子面板，显示当前章节对应的审阅约束及其满足状态（✓/✗/⚠）

---

## P0-4：章节字数控制

### 问题

番茄平台标准 2000-2200 字/章。AI 两大偏差：幻觉暴走（突然 4000 字）和凑字数（车轱辘话）。偏差直接影响完读率权重计算。

### 设计

三层控制：

**第一层：Prompt 约束** 注入每章生成 prompt：

```
【硬性字数要求】
- 本章正文：2000-2200 中文字符
- 禁止超过 2300，禁止低于 1800
- 不要为凑字重复表述
- 情节在 2000 字内讲完 → 用追加钩子/场景细节自然补足
```

**第二层：生成后检测 + 调整**

**新增 `novel_generator/word_count_control.py`**：

```python
@dataclass
class WordCount:
    chinese: int    # 中文字符数
    total: int      # 总字符数

def measure_chapter(text: str) -> WordCount: ...

def adjust_chapter(text: str, target_range: tuple = (2000, 2200)) -> AdjustedChapter:
    """
    策略：
    - 2000-2200 → 直接通过
    - 2201-2500 → LLM 精简（保留钩子，删环境/独白冗余）
    - >2500 → 强制精简 + 警告
    - 1800-2000 → LLM 扩展（感官细节 + 心理反应）
    - <1800 → 强制扩展 + 警告（最多 2 轮，不满足标"字数偏差"）
    """
    return AdjustedChapter(text=..., final_count=..., adjustments=0, warning=...)
```

**精简约束**：保留所有钩子、关键对话信息；优先删环境描写/内心独白冗余
**扩展约束**：优先感官细节（声/触/味）、角色瞬间心理；禁止灌水；扩展后重检钩子密度

**第三层：最终校验**

`finalize_chapter()` 中增加字数检测作为收尾步骤：
- 在区间内 → 正常 finalize
- 偏差 <10% → finalize + 标记 `word_count_deviation`
- 偏差 >10% → LLM 调整（最多 2 轮）→ 仍不满足则标记供人工处理

---

## 文件交付清单

| 模块 | 新增文件 | 修改文件 |
|------|----------|----------|
| P0-1 | `novel_generator/title_generator.py` | `outline_reviewer/server.py`, `webui/index.html` |
| P0-2 | `novel_generator/hook_engine.py` | `novel_generator/chapter.py`, `webui/reader.html` |
| P0-3 | `novel_generator/review_constraints.py` | `novel_generator/chapter.py`, `novel_generator/finalization.py`, `outline_reviewer/server.py`, `webui/index.html`, `webui/reader.html` |
| P0-4 | `novel_generator/word_count_control.py` | `novel_generator/chapter.py`, `novel_generator/finalization.py` |

## API 端点汇总

| 端点 | 方法 | 所属模块 |
|------|------|----------|
| `/api/outlines/{id}/generate-titles` | POST | P0-1 |
| `/api/outlines/{id}/generate-synopsis` | POST | P0-1 |
| `/api/novels/{name}/chapters/{n}/hooks` | GET | P0-2 |
| `/api/novels/{name}/chapters/{n}/cliffhanger` | POST | P0-2 |
| `/api/outlines/{id}/constraints` | GET | P0-3 |
| `/api/queue/start-novel` | POST | P0-3 |
| `/api/novels/{name}/constraints` | GET | P0-3 |

## 数据流

```
书名/简介生成 (P0-1)
  │
  ▼
审阅器 edits + annotations
  │
  ▼
审阅约束提取 (P0-3)
  │
  ├── replaced_content → 覆盖 architecture
  └── constraints → 注入每章 prompt
       │
       ▼
    章节生成 (chapter.py)
       ├── 钩子指令注入 (P0-2)
       ├── 字数约束注入 (P0-4)
       └── 生成后一致性检查 (P0-3)
       │
       ▼
    生成后处理
       ├── 字数检测 + 调整 (P0-4)
       ├── 钩子密度扫描 (P0-2)
       └── 约束满足度评估 (P0-3)
       │
       ▼
    阅读器展示
       ├── 钩子密度热力条 (P0-2)
       └── 约束对照面板 (P0-3)
```
