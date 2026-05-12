"""
Rewrite Agent - Anti-AI-flavor text rewrite with context wrapping.

Flow:
  selected text + context_window (300 chars before + 300 after)
  + style preset + custom instruction
  -> LLM rewrite
  -> cleaned output
"""

import re
from typing import Optional

# Anti-AI-flavor base system prompt
REWRITE_SYSTEM_PROMPT = """你是一个网文改写器。你的唯一任务是改写用户选中的文本片段。

【全局禁止规则】
- 禁止使用任何比喻修辞（尤其是"如同一把利剑""仿佛在诉说""宛如"）
- 禁止使用文艺腔词汇：蓦然、红尘、羁绊、宿命、温柔了岁月、惊艳了时光
- 禁止使用"他感到""他觉得""他意识到""他心想"等心理概括句式
- 禁止使用"一切""似乎""仿佛""显得"等虚拟/模糊语气词
- 禁止使用"就这样""xxx地说""xxx地做了xxx"等叙事废话
- 禁止使用重复的成语和套话

【改写原则】
- Show, Don't Tell：用外部动作/对话/环境代替内心独白
- 短句：每句不超过 20 字，用句号替代逗号
- 具体：用具体的感官细节（声/触/味/色）替代抽象概括
- 对话：去礼貌化，人物对话直接、简短、带刺
- 节奏：动作→反应→对话→动作，不要停留在同一层面

【输出格式】
直接输出改写后的文本片段，不要加任何前缀、后缀或解释。不要用 markdown 代码块包裹。
输出长度应与原文相近，±20% 之内。"""


def build_rewrite_prompt(
    before_context: str,
    selected_text: str,
    after_context: str,
    instruction: str,
    style_extra: str = ""
) -> str:
    """Build the rewrite prompt with context wrapping.

    Args:
        before_context: Up to 300 chars before the selection
        selected_text: The user-selected text to rewrite
        after_context: Up to 300 chars after the selection
        instruction: Custom user instruction
        style_extra: Extra system prompt fragment from style preset
    """
    parts = [
        "【上下文 - 前文】",
        before_context or "（无）",
        "",
        "【需要改写的文本】",
        selected_text,
        "",
        "【上下文 - 后文】",
        after_context or "（无）",
        "",
        "【改写指令】",
        instruction,
    ]

    if style_extra:
        parts.extend(["", "【风格要求】", style_extra])

    parts.extend([
        "",
        "请仅输出改写后的文本，保持长度与原文相近。不要加任何前缀说明。"
    ])

    return "\n".join(parts)


def extract_context(full_text: str, start_pos: int, end_pos: int, window: int = 300) -> tuple:
    """Extract selected text and context window.

    Args:
        full_text: Full chapter text
        start_pos: Start character position of selection
        end_pos: End character position of selection
        window: Context window size in characters (default 300)

    Returns:
        (before_context, selected_text, after_context)
    """
    selected_text = full_text[start_pos:end_pos]

    before_start = max(0, start_pos - window)
    before_context = full_text[before_start:start_pos]

    after_end = min(len(full_text), end_pos + window)
    after_context = full_text[end_pos:after_end]

    return before_context, selected_text, after_context


def clean_rewrite_output(raw: str) -> str:
    """Clean LLM output - strip markdown fences and common prefixes."""
    # Strip markdown code fences
    cleaned = re.sub(r'```(?:[\w]*)?\s*\n?', '', raw)
    cleaned = re.sub(r'\n?```', '', cleaned)

    # Strip common AI preamble patterns
    cleaned = re.sub(r'^以下是?改写.*?[：:]\s*', '', cleaned)
    cleaned = re.sub(r'^改写后.*?[：:]\s*', '', cleaned)
    cleaned = re.sub(r'^好的[，,].*?\n', '', cleaned)

    return cleaned.strip()
