# novel_generator/word_count_control.py
# -*- coding: utf-8 -*-
"""Chapter word count measurement and adjustment for Tomato Novel platform standards (2000-2200 chars)."""
import re
import logging
from dataclasses import dataclass
from typing import Optional

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

TARGET_MIN = 2000
TARGET_MAX = 2200
HARD_MIN = 1800
HARD_MAX = 2500

WORD_COUNT_CONSTRAINT = f"""【硬性字数要求】
- 本章正文字数：{TARGET_MIN}-{TARGET_MAX} 中文字符
- 禁止超过 {TARGET_MAX}，禁止低于 {TARGET_MIN}
- 不要为了凑字数而重复表述
- 如果当前情节在 {TARGET_MIN} 字内讲完，用追加钩子/场景细节自然补足，不要硬拖"""


@dataclass
class WordCount:
    chinese: int
    total: int


@dataclass
class AdjustedChapter:
    text: str
    final_count: int
    adjustments: int
    warning: Optional[str] = None


def measure_chapter(text: str) -> WordCount:
    chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
    total_chars = len(text)
    return WordCount(chinese=chinese_chars, total=total_chars)


def build_trim_prompt(text: str, excess: int) -> str:
    return f"""请精简以下小说章节，删除约 {excess} 个中文字符（当前超出目标字数）。

精简规则（必须严格遵守）：
1. 保留所有钩子和悬念节点 — 这是最高优先级
2. 保留所有关键对话 — 对话中的信息不能丢失
3. 优先删除：环境描写的冗余部分、内心独白的重复表述、过渡性叙述
4. 禁止删除：角色间的对话、情节转折点、章末钩子

目标字数范围：{TARGET_MIN}-{TARGET_MAX} 中文字符

原文：
{text}

请输出精简后的完整章节："""


def build_expand_prompt(text: str, deficit: int) -> str:
    return f"""请扩展以下小说章节，增加约 {deficit} 个中文字符（当前不足目标字数）。

扩展规则（必须严格遵守）：
1. 优先增加场景的感官细节（环境声、触感、气味、光线变化）
2. 补充角色的瞬间心理反应（对话后、动作后的内心波动）
3. 可以增加一个额外的微场景来引入新的钩子
4. 禁止用废话凑字数 — 禁止重复已有信息 — 禁止无意义的环境描写堆砌
5. 扩展后不能稀释原有的钩子密度

目标字数范围：{TARGET_MIN}-{TARGET_MAX} 中文字符

原文：
{text}

请输出扩展后的完整章节："""


def adjust_chapter(
    text: str,
    target_range: tuple = (TARGET_MIN, TARGET_MAX),
    llm_adapter=None,
    max_rounds: int = 2
) -> AdjustedChapter:
    """
    Adjust chapter word count to target range.
    Returns the adjusted text. If llm_adapter is None, returns original with warning.
    """
    wc = measure_chapter(text)
    low, high = target_range
    adjustments = 0
    warning = None

    if low <= wc.chinese <= high:
        return AdjustedChapter(text=text, final_count=wc.chinese, adjustments=0)

    current_text = text

    for _ in range(max_rounds):
        wc = measure_chapter(current_text)

        if low <= wc.chinese <= high:
            break

        if llm_adapter is None:
            deviation_pct = abs(wc.chinese - ((low + high) // 2)) / ((low + high) // 2) * 100
            warning = f"word_count_deviation: {wc.chinese} chars ({deviation_pct:.0f}% off target, no LLM adapter for adjustment)"
            break

        if wc.chinese > high:
            excess = wc.chinese - ((low + high) // 2)
            prompt = build_trim_prompt(current_text, excess)
        else:
            deficit = ((low + high) // 2) - wc.chinese
            prompt = build_expand_prompt(current_text, deficit)

        try:
            from novel_generator.common import invoke_with_cleaning
            result = invoke_with_cleaning(llm_adapter, prompt)
            if result and len(re.findall(r'[\u4e00-\u9fff]', result)) > HARD_MIN:
                current_text = result
                adjustments += 1
            else:
                warning = f"word_count_deviation: adjustment round {adjustments+1} returned empty or too short"
                break
        except Exception as e:
            logging.warning(f"Word count adjustment failed: {e}")
            warning = f"word_count_deviation: adjustment error: {e}"
            break

    final_wc = measure_chapter(current_text)
    if not warning and (final_wc.chinese < low or final_wc.chinese > high):
        deviation_pct = abs(final_wc.chinese - ((low + high) // 2)) / ((low + high) // 2) * 100
        if deviation_pct > 10:
            warning = f"word_count_deviation: {final_wc.chinese} chars ({deviation_pct:.0f}% off target after {adjustments} adjustments)"

    return AdjustedChapter(text=current_text, final_count=final_wc.chinese, adjustments=adjustments, warning=warning)
