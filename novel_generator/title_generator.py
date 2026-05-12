# novel_generator/title_generator.py
# -*- coding: utf-8 -*-
"""Tomato Novel platform title and synopsis generator. Optimized for click-through (吸量)."""
import json
import logging

logging.basicConfig(
    filename='app.log',
    filemode='a',
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

TITLE_SYSTEM_PROMPT = """你是一位番茄小说平台的资深编辑，专精于男频爆款书名策划。

## 书名规则
- 长度：16-22 字，微短剧风长句体
- 公式：身份 + 动作 + 反差 + 情绪钩子
- 热门模板参考：听劝后/重生后/系统给了我/开局xxx/都重生了谁还xxx
- 必须包含信息差或悬念，让读者产生"然后呢？"的冲动
- 必须具体，不能抽象 — 给出具体的身份、具体的动作、具体的反差

## 绝对禁止
- 文艺腔（如"那些年""浮生若梦"）
- 抽象名（如"命运""时光"）
- 两字名（如"重生""逆袭"）
- 任何括号、标点堆砌、emoji
- 与已有爆款书名高度雷同

## 输出格式
为每个候选书名输出 JSON：
```json
[
  {
    "title": "候选书名",
    "score": 85,
    "dimensions": {
      "信息密度": 90,
      "悬念强度": 85,
      "差异化": 80,
      "情绪张力": 85
    },
    "reason": "评分理由，30字以内"
  }
]
```

输出 5 个候选书名，严格 JSON 数组格式，不要额外文字。"""

SYNOPSIS_SYSTEM_PROMPT = """你是一位番茄小说平台的资深编辑。

## 简介规则
- 50 字以内
- 结构：核心设定（1 句）+ 情感钩子（1 句）+ 悬念留白（1 句）
- 必须有让读者"不看完睡不着"的钩子
- 禁止剧透核心反转
- 用具体的场景暗示，不要抽象概括

## 输出格式
```json
{
  "synopsis": "简介内容",
  "char_count": 45,
  "hook_tags": ["系统反套路", "都市异能", "生存博弈"]
}
```
严格 JSON 格式，不要额外文字。"""


def _create_client():
    """Create OpenAI client from project config."""
    import os
    project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_path = os.path.join(project_dir, "config.json")
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    provider = "NetEase LeiHuo"
    llm_cfg = config["llm_configs"][provider]
    from openai import OpenAI
    return OpenAI(api_key=llm_cfg["api_key"], base_url=llm_cfg["base_url"].rstrip("/") + "/v1")


def _call_llm(system_prompt: str, user_prompt: str, temperature: float = 0.8, max_tokens: int = 2048) -> str:
    """Call LLM with retry."""
    import time
    client = _create_client()
    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model="gpt-5.4",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return resp.choices[0].message.content
        except Exception as e:
            logging.warning(f"LLM retry {attempt+1}/3: {e}")
            time.sleep(2)
    raise RuntimeError("LLM call failed after 3 retries")


def _extract_titles(outline_data: dict) -> str:
    """Extract relevant content from outline for title generation."""
    sections = outline_data.get("sections", {})
    parts = []
    title_text = sections.get("书名字", "") or sections.get("_title", "")
    if title_text:
        parts.append(f"当前书名：{title_text.split(chr(10))[0].strip()}")
    sell_point = sections.get("一句话卖点", "")
    if sell_point:
        parts.append(f"一句话卖点：{sell_point[:100]}")
    core_setting = sections.get("核心设定", "")
    if core_setting:
        parts.append(f"核心设定：{core_setting[:200]}")
    if not parts:
        parts.append(f"题材：{outline_data.get('name', '未知')}")
        parts.append(f"标签：{outline_data.get('tag', '')}")
    return "\n".join(parts)


def generate_titles(outline_data: dict, count: int = 5) -> list[dict]:
    """Generate title candidates with scores."""
    context = _extract_titles(outline_data)
    user_prompt = f"""请基于以下小说大纲，生成 {count} 个番茄小说风格的爆款书名候选：

{context}

注意：书名必须 16-22 字长句体，必须有信息差/悬念/反差。"""
    raw = _call_llm(TITLE_SYSTEM_PROMPT, user_prompt, temperature=0.85, max_tokens=2048)
    try:
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1]
            if raw.endswith("```"):
                raw = raw[:-3]
        result = json.loads(raw)
        if isinstance(result, list):
            return result[:count]
    except json.JSONDecodeError:
        logging.warning("Failed to parse title JSON, returning raw")
    return [{"title": raw[:50], "score": 0, "dimensions": {}, "reason": "JSON解析失败"}]


def generate_synopsis(outline_data: dict, selected_title: str) -> dict:
    """Generate synopsis for a selected title."""
    context = _extract_titles(outline_data)
    user_prompt = f"""请为以下小说生成番茄风格的简介：

书名：{selected_title}

小说信息：
{context}

请输出 50 字以内的爆款简介。"""
    raw = _call_llm(SYNOPSIS_SYSTEM_PROMPT, user_prompt, temperature=0.8, max_tokens=1024)
    try:
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1]
            if raw.endswith("```"):
                raw = raw[:-3]
        result = json.loads(raw)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        logging.warning("Failed to parse synopsis JSON")
    return {"synopsis": raw[:100], "char_count": len(raw), "hook_tags": []}
