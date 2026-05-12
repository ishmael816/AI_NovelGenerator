# novel_generator/hook_engine.py
# -*- coding: utf-8 -*-
"""Hook detection and cliffhanger generation for Tomato Novel platform retention optimization."""
import json
import logging

logging.basicConfig(
    filename='app.log',
    filemode='a',
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

HOOK_REQUIREMENT_PROMPT = """【硬性钩子要求】
- 每 500-800 字必须包含至少一个微钩子（信息差/冲突暗示/情感张力/能力展示/认知反转）
- 章末最后 2-3 段必须是高强度悬念钩子（让读者必须点下一章）
- 禁止平铺直叙。禁止"一切都很顺利"式的平静结尾。禁止"就这样，xxx"式的叙事结束语
- 五种钩子类型示例：
  * 信息钩子：暗示有重要信息未揭露 → "她看了一眼诊断报告，脸色瞬间变了"
  * 冲突钩子：引入对抗或威胁 → "林昼还没说完，办公室门被一脚踹开"
  * 反转钩子：颠覆已有认知 → "弹窗第3条的真正意思，他三个月后才懂"
  * 情感钩子：高张力情感时刻 → "赵一帆删掉了代码。这是他这辈子第一次背叛林昼"
  * 能力钩子：展示/暗示主角隐藏能力 → "他把手机转向对方——数字让对方瞳孔骤缩" """

HOOK_DETECT_SYSTEM = """你是一位专业的小说钩子分析师。请扫描以下章节，标记所有钩子（hook）的位置和强度。

钩子类型定义：
- 信息钩子：暗示有重要信息未揭露，引发读者好奇心
- 冲突钩子：引入对抗、威胁或紧张关系
- 反转钩子：颠覆已有认知或预期
- 情感钩子：高张力的情感时刻、关系转折
- 能力钩子：展示或暗示主角隐藏/特殊能力

对每个钩子评估强度 0-1（0.7+ 为强力钩子，0.4-0.7 为中等，<0.4 为弱钩子）。
特别标注章末（最后 3 段）是否有强度 ≥0.8 的终局钩子。

输出 JSON 格式：
```json
{
  "hooks": [{"position": 156, "type": "信息钩子", "strength": 0.7, "text_snippet": "原文片段（15字内）"}],
  "density": 3.2,
  "distribution": {"前1/3": 3, "中1/3": 2, "后1/3": 1},
  "end_cliffhanger": false,
  "score": 72,
  "summary": "整体评价，50字内"
}
```
严格 JSON，不要额外文字。"""

CLIFFHANGER_SYSTEM = """你是番茄小说平台的爆款章末钩子专家。

基于当前章节和下章蓝图，生成 3 个章末钩子候选。每个钩子必须：
1. 让读者产生"必须点下一章"的冲动
2. 与本章内容自然衔接
3. 暗示/指向下一章的核心冲突或反转
4. 20-40 字，具体而非抽象

输出 JSON 数组：
```json
[
  {"text": "钩子1", "type": "信息钩子", "strength": 0.9},
  {"text": "钩子2", "type": "冲突钩子", "strength": 0.85},
  {"text": "钩子3", "type": "反转钩子", "strength": 0.8}
]
```
严格 JSON，不要额外文字。"""


def _create_client():
    import os
    project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_path = os.path.join(project_dir, "config.json")
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    provider = "NetEase LeiHuo"
    try:
        llm_cfg = config["llm_configs"][provider]
    except KeyError as e:
        raise RuntimeError(f"Config missing provider '{provider}': {e}") from e
    from openai import OpenAI
    return OpenAI(api_key=llm_cfg["api_key"], base_url=llm_cfg["base_url"].rstrip("/") + "/v1")


def _call_llm(system_prompt: str, user_prompt: str, temperature: float = 0.3, max_tokens: int = 2048) -> str:
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


def detect_hooks(chapter_text: str) -> dict:
    """Analyze a chapter and return hook distribution report."""
    if not chapter_text or len(chapter_text) < 100:
        return {"hooks": [], "density": 0, "distribution": {}, "end_cliffhanger": False, "score": 0, "summary": "内容过短，无法分析"}

    max_len = 6000
    text_to_analyze = chapter_text if len(chapter_text) <= max_len else chapter_text[:max_len] + "\n\n[... 后续内容截断 ...]"

    user_prompt = f"请分析以下小说章节的钩子分布：\n\n{text_to_analyze}"
    raw = _call_llm(HOOK_DETECT_SYSTEM, user_prompt, temperature=0.3, max_tokens=2048)

    try:
        import re as _re
        raw = raw.strip()
        m = _re.search(r'```(?:json)?\s*\n(.*?)\n```', raw, _re.DOTALL)
        if m:
            raw = m.group(1).strip()
        result = json.loads(raw)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        logging.warning("Failed to parse hook detection JSON")
    return {"hooks": [], "density": 0, "distribution": {}, "end_cliffhanger": False, "score": 0, "summary": "解析失败"}


def generate_cliffhanger(chapter_content: str, next_blueprint: str) -> list[dict]:
    """Generate cliffhanger candidates for chapter ending."""
    max_len = 1500
    ch_excerpt = chapter_content[-max_len:] if len(chapter_content) > max_len else chapter_content
    bp_excerpt = next_blueprint[:800] if next_blueprint else "（无下章蓝图）"

    user_prompt = f"""本章末尾内容：
{ch_excerpt}

下一章蓝图：
{bp_excerpt}

请基于以上内容，生成 3 个章末钩子候选。"""
    raw = _call_llm(CLIFFHANGER_SYSTEM, user_prompt, temperature=0.7, max_tokens=1024)

    try:
        import re as _re
        raw = raw.strip()
        m = _re.search(r'```(?:json)?\s*\n(.*?)\n```', raw, _re.DOTALL)
        if m:
            raw = m.group(1).strip()
        result = json.loads(raw)
        if isinstance(result, list):
            return result
    except json.JSONDecodeError:
        logging.warning("Failed to parse cliffhanger JSON")
    return [{"text": raw[:80] if raw else "生成失败", "type": "信息钩子", "strength": 0.5}]
