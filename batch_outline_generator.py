# -*- coding: utf-8 -*-
"""
番茄小说男频高频题材批量大纲生成器
基于2026年3月番茄平台真实数据，覆盖10大热门赛道。
所有大纲生成后按索引落盘，供人工审核。
"""
import sys
import os
import json
import time
from datetime import datetime

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_DIR)

from openai import OpenAI

# ── Config ──
CONFIG_PATH = os.path.join(PROJECT_DIR, "config.json")
with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    config = json.load(f)

provider = "NetEase LeiHuo"
llm_cfg = config["llm_configs"][provider]

client = OpenAI(api_key=llm_cfg["api_key"], base_url=llm_cfg["base_url"].rstrip("/") + "/v1")
MODEL = "gpt-5.4"
TEMPERATURE = 0.75
MAX_TOKENS = 4096

OUTPUT_DIR = os.path.join(PROJECT_DIR, "output", "outlines")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ── Top 10 高频题材定义（基于2026年3月番茄首秀+在读数据）─
THEMES = [
    {
        "id": "01",
        "tag": "urban-brainhole",
        "name": "都市脑洞",
        "market_share": "11%（首秀新书占比第一）",
        "competition": "红海",
        "formula": "日常生活 × 超现实设定 × 密集爽点",
        "references": "《我创造了怪物序列！》《我在精神病院学斩神》",
        "prompt_seed": "一个普通都市青年，在某天获得了一个荒诞但强大的特殊能力，这个能力在日常生活和职场中引发连锁反应，逐渐揭开隐藏在现代都市之下的超凡世界。核心卖点：脑洞设定 + 都市代入感 + 爽点密集。"
    },
    {
        "id": "02",
        "tag": "eastern-xianxia",
        "name": "东方仙侠",
        "market_share": "10%（首秀新书占比第二）",
        "competition": "红海",
        "formula": "修仙体系 × 独特金手指 × 升级打怪",
        "references": "《凡骨》《洪荒，我把怨念当功德，大道懵了》",
        "prompt_seed": "一个修仙世界的小人物，意外获得与众不同的金手指（与主流修仙路线完全相反），在修真界一步步崛起。核心卖点：反套路修仙 + 境界体系创新 + 洪荒世界观。"
    },
    {
        "id": "03",
        "tag": "fantasy-brainhole",
        "name": "玄幻脑洞",
        "market_share": "10%（与仙侠并列前三）",
        "competition": "红海",
        "formula": "异世界 × 脑洞设定 × 体系构建",
        "references": "《系统赋我长生，活着终会无敌》《梦里和娘子生娃后，她们都成真了》",
        "prompt_seed": "主角进入一个规则完全不同的异世界，或者现实世界被某种超凡规则覆盖，他必须在理解规则、利用规则的过程中生存并崛起。核心卖点：独特世界观 + 规则体系博弈 + 成长线清晰。"
    },
    {
        "id": "04",
        "tag": "system-anti-trope",
        "name": "系统反套路",
        "market_share": "跨赛道高增长（单周增量44万+爆款）",
        "competition": "蓝海机会",
        "formula": "系统/金手指 × 预期违背 × 人性困境",
        "references": "《都重生了才告诉我全家是反派》《开局地摊卖大力》",
        "prompt_seed": "主角获得了一个表面上逆天的系统/金手指，但随着使用深入，发现系统的每一份馈赠都暗中标注了惊人的代价，他必须在利用系统和反制系统之间找到平衡。核心卖点：反套路设定 + 人性博弈 + 层层反转。"
    },
    {
        "id": "05",
        "tag": "rebirth-counterattack",
        "name": "重生逆袭",
        "market_share": "经典长青题材，持续高热度",
        "competition": "红海（需差异化）",
        "formula": "重生 × 信息差 × 逆天改命",
        "references": "《莫欺老年穷：一天涨一年功力！》《重生：官运亨通》",
        "prompt_seed": "主角带着前世记忆重生到人生关键节点，利用先知优势逆天改命，但历史的蝴蝶效应导致一切逐渐偏离轨道，他不得不面对完全陌生的挑战。核心卖点：重生信息差 + 蝴蝶效应悬念 + 打脸爽感。"
    },
    {
        "id": "06",
        "tag": "apocalypse-scifi",
        "name": "末世科幻",
        "market_share": "稳定增长（172万+在读头部作品）",
        "competition": "蓝海",
        "formula": "末世灾难 × 生存博弈 × 人性考验",
        "references": "《全球冰封：我打造了末日安全屋》《末日生存方案供应商》",
        "prompt_seed": "一场前所未有的全球性灾难降临（冰封/丧尸/天灾），主角拥有一个与生存直接相关的特殊能力或优势，在末世中不仅要活下去，还要保护身边的人，重建秩序。核心卖点：末世代入感 + 生存策略 + 人性选择。"
    },
    {
        "id": "07",
        "tag": "historical-strategy",
        "name": "历史权谋",
        "market_share": "约19%（参考起点三江榜），番茄增长中",
        "competition": "中等竞争",
        "formula": "真实历史背景 × 穿越/重生 × 智斗权谋",
        "references": "《冒姓琅琊》（短剧播放破10亿）",
        "prompt_seed": "主角穿越/重生到某个真实历史时期（魏晋/宋/明等），凭借超越时代的见识在现代社会中求生、崛起，在世家门阀、朝堂权谋中步步为营。核心卖点：考据式历史细节 + 智斗博弈 + 身份逆袭。"
    },
    {
        "id": "08",
        "tag": "rule-mystery",
        "name": "规则怪谈",
        "market_share": "700万追更头部作品引领，高口碑赛道",
        "competition": "蓝海",
        "formula": "诡异规则 × 死亡博弈 × 智斗解密",
        "references": "《十日终焉》（评分9.9/700万人追更）",
        "prompt_seed": "主角被卷入一个由诡异规则支配的游戏/空间，每一条规则背后都隐藏着致命陷阱，他必须在无数规则中找出漏洞，一步步解开背后的真相。核心卖点：烧脑智斗 + 规则解谜 + 人性黑暗面。"
    },
    {
        "id": "09",
        "tag": "expert-descends",
        "name": "高手下山",
        "market_share": "持续稳定的流量池（战神赘婿变体）",
        "competition": "红海",
        "formula": "隐藏身份 × 都市装逼 × 层层打脸",
        "references": "《我，满配二郎神，绑定软糯校花！》《高手下山，我家师姐太宠我了》",
        "prompt_seed": "一个拥有超凡能力/背景的人因为某种原因隐藏身份进入都市生活，在遭遇挑衅和危机时被迫展露实力，每一层身份的揭晓都带来新的震撼。核心卖点：身份反转爽感 + 装逼打脸 + 隐藏身份层层揭开。"
    },
    {
        "id": "10",
        "tag": "derivative-fanfic",
        "name": "衍生同人",
        "market_share": "十日首秀占比高达50%爆款率",
        "competition": "蓝海（需注意版权）",
        "formula": "经典IP世界观 × 原创主角 × 降维打击",
        "references": "《海贼的巅峰！从罗杰团实习生开始》《火影：灭族前夕，系统救我于水火》",
        "prompt_seed": "主角穿越到经典动漫/影视/小说世界（海贼/火影/三国等），利用对剧情的先知优势和独特金手指，在熟悉又陌生的世界中开辟全新道路。核心卖点：IP情怀 + 先知优势 + 剧情改写爽感。"
    },
]

SYSTEM_PROMPT = """你是一位资深网文编辑和故事架构师，专精于番茄小说平台的男频爆款内容策划。

你的任务是为给定题材设计一个完整的商业小说大纲。请严格遵循以下格式输出，不要添加额外内容：

## 书名字
（16-22字，微短剧风长句体，公式：身份+动作+反差）

## 一句话卖点
（50字以内，包含核心设定+情感钩子）

## 核心设定
- 世界观：
- 金手指/系统：
- 力量体系/规则：
- 核心矛盾：

## 主角人设
- 姓名年龄：
- 身份背景：
- 性格特点：
- 核心欲望：
- 成长弧线：

## 三幕结构
### 第一幕：建立（1-30%篇幅）
### 第二幕：对抗（30-80%篇幅）
### 第三幕：解决（80-100%篇幅）

## 前10章详细大纲
（每章写清楚：章节标题 + 核心情节 + 结尾钩子，每章约3-5句话）

## 商业卖点清单
- 爽点类型：
- 悬念设计：
- 反转节点：
- 差异化定位：

## 目标读者画像
- 年龄：
- 阅读偏好：
- 付费意愿触发点："""


def call_llm(prompt: str, max_tokens: int = 4096) -> str:
    """调用 LLM，带重试"""
    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=TEMPERATURE,
                max_tokens=max_tokens,
            )
            return resp.choices[0].message.content
        except Exception as e:
            print(f"  [Retry {attempt+1}/3] LLM error: {e}")
            time.sleep(3)
    raise RuntimeError("LLM call failed after 3 retries")


def generate_outline(theme: dict) -> str:
    """为一个题材生成大纲"""
    prompt = f"""请为以下番茄小说男频热门题材设计一个完整的商业小说大纲：

【题材名称】{theme['name']}
【标签】{theme['tag']}
【市场数据】{theme['market_share']}
【竞争程度】{theme['competition']}
【爆款公式】{theme['formula']}
【对标作品】{theme['references']}

【创作方向】
{theme['prompt_seed']}

请按照系统提示的格式，输出完整大纲。注意书名必须是16-22字的长句体微短剧风格。"""

    print(f"  Generating outline for: {theme['name']}...")
    content = call_llm(prompt, max_tokens=MAX_TOKENS)
    return content


def save_outline(theme: dict, content: str, timestamp: str):
    """保存大纲到磁盘"""
    safe_tag = theme['tag']
    idx = theme['id']

    # JSON 格式（结构化元数据 + 内容）
    json_path = os.path.join(OUTPUT_DIR, f"outline_{idx}_{safe_tag}.json")
    record = {
        "index": idx,
        "tag": safe_tag,
        "name": theme["name"],
        "market_share": theme["market_share"],
        "competition": theme["competition"],
        "formula": theme["formula"],
        "references": theme["references"],
        "content": content,
        "generated_at": timestamp,
        "model": MODEL,
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)

    # TXT 格式（人类可读）
    txt_path = os.path.join(OUTPUT_DIR, f"outline_{idx}_{safe_tag}.txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(f"# {theme['name']} — 小说大纲\n")
        f.write(f"# 索引: {idx} | 标签: {safe_tag}\n")
        f.write(f"# 市场数据: {theme['market_share']} | 竞争: {theme['competition']}\n")
        f.write(f"# 对标: {theme['references']}\n")
        f.write(f"# 生成时间: {timestamp}\n")
        f.write("=" * 60 + "\n\n")
        f.write(content)

    return json_path, txt_path


def generate_index(themes, timestamp):
    """生成主索引文件"""
    idx_path = os.path.join(OUTPUT_DIR, "index.md")
    lines = [
        "# 番茄小说男频高频题材批量大纲索引",
        "",
        f"> 生成时间: {timestamp}",
        f"> 模型: {MODEL}",
        f"> 数据基准: 2026年3月番茄平台首秀+在读数据",
        "",
        "## 十大题材概览",
        "",
        "| # | 题材 | 标签 | 市场份额 | 竞争 | 爆款公式 |",
        "|---|------|------|----------|------|----------|",
    ]
    for t in THEMES:
        lines.append(
            f"| {t['id']} | {t['name']} | `{t['tag']}` | {t['market_share']} | {t['competition']} | {t['formula']} |"
        )

    lines += [
        "",
        "## 文件索引",
        "",
    ]
    for t in THEMES:
        txt = f"outline_{t['id']}_{t['tag']}.txt"
        json_f = f"outline_{t['id']}_{t['tag']}.json"
        lines.append(f"- **{t['id']}. {t['name']}** — [`{txt}`]({txt}) | [`{json_f}`]({json_f})")

    lines += [
        "",
        "## 审阅清单",
        "",
        "逐项检查每份大纲：",
        "",
        "- [ ] 书名是否符合16-22字微短剧风格",
        "- [ ] 核心设定是否有独特性（区别于同类作品）",
        "- [ ] 金手指/系统是否有清晰的代价机制",
        "- [ ] 主角人设是否立体（有缺陷、有成长弧线）",
        "- [ ] 三幕结构是否完整（建立-对抗-解决）",
        "- [ ] 前10章每章是否有明确的爽点/悬念钩子",
        "- [ ] 商业卖点是否清晰可执行",
        "- [ ] 对标作品定位是否准确",
    ]

    with open(idx_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return idx_path


def main():
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    print("=" * 60)
    print("  番茄小说男频 — 批量大纲生成器")
    print(f"  题材数: {len(THEMES)} | 模型: {MODEL}")
    print("=" * 60)

    results = []
    for i, theme in enumerate(THEMES):
        print(f"\n[{i+1}/{len(THEMES)}] {theme['id']} - {theme['name']}", flush=True)
        try:
            content = generate_outline(theme)
            json_path, txt_path = save_outline(theme, content, timestamp)
            print(f"  -> Saved: {os.path.basename(txt_path)}", flush=True)
            results.append({"theme": theme["name"], "status": "OK", "file": txt_path})
        except Exception as e:
            print(f"  -> FAILED: {e}", flush=True)
            results.append({"theme": theme["name"], "status": "FAILED", "error": str(e)})

        # 避免请求过快
        if i < len(THEMES) - 1:
            time.sleep(2)

    # 生成索引
    idx_path = generate_index(THEMES, timestamp)
    print(f"\n{'='*60}")
    print(f"  Index: {idx_path}")
    print(f"  Results: {sum(1 for r in results if r['status'] == 'OK')}/{len(results)} OK")
    print(f"{'='*60}")

    # 输出结果摘要
    print("\n  Summary:")
    for r in results:
        status = "[OK]" if r["status"] == "OK" else "[FAIL]"
        print(f"    {status} {r['theme']}")


if __name__ == "__main__":
    main()
