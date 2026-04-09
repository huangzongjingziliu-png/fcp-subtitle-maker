#!/usr/bin/env python3
"""
FCPXML Subtitle Generator - Final Cut Pro X 10.6+ Compatible
生成符合 FCPXML 1.10 DTD 规范的字幕文件

功能：
- 智能标点清理：去除顿号、分号、逗号等，保留引号（「」）、书名号（《》）、间隔号（·）、连接号（—）
- 双语字幕支持：中英文双语，中文在上、英文在下
- text-style-def 内联在 title 内部
- 使用 FCP 内置 Basic Title effect
"""

import json
import sys
import math
import re
import subprocess
from fractions import Fraction


# ─── 翻译功能 ─────────────────────────────────────────────

TRANSLATION_CACHE = {}

def translate_text(text, source_lang='zh', target_lang='en'):
    """
    调用翻译 API 将中文翻译为英文。
    优先使用 DeepL，其次使用 OpenAI API。
    返回翻译后的文本或空字符串（如果翻译失败）。
    """
    if not text or not text.strip():
        return ""
    
    text = text.strip()
    cache_key = f"{source_lang}:{target_lang}:{text}"
    if cache_key in TRANSLATION_CACHE:
        return TRANSLATION_CACHE[cache_key]
    
    # 尝试 DeepL API (需要 DEEPL_API_KEY 环境变量)
    try:
        import os
        deepl_key = os.environ.get('DEEPL_API_KEY')
        if deepl_key:
            import urllib.request
            import urllib.parse
            url = "https://api-free.deepl.com/v2/translate"
            data = urllib.parse.urlencode({
                'auth_key': deepl_key,
                'text': text,
                'source_lang': source_lang.upper(),
                'target_lang': target_lang.upper()
            }).encode()
            req = urllib.request.Request(url, data=data, method='POST')
            with urllib.request.urlopen(req, timeout=10) as response:
                result = json.loads(response.read().decode())
                if 'translations' in result and len(result['translations']) > 0:
                    translated = result['translations'][0]['text']
                    TRANSLATION_CACHE[cache_key] = translated
                    return translated
    except Exception as e:
        pass
    
    # 尝试 OpenAI API (需要 OPENAI_API_KEY 环境变量)
    try:
        import os
        openai_key = os.environ.get('OPENAI_API_KEY')
        if openai_key:
            import urllib.request
            url = "https://api.openai.com/v1/chat/completions"
            headers = {
                'Authorization': f'Bearer {openai_key}',
                'Content-Type': 'application/json'
            }
            payload = json.dumps({
                'model': 'gpt-3.5-turbo',
                'messages': [
                    {'role': 'system', 'content': 'You are a professional translator. Translate the following Chinese text to English. Keep it concise and suitable for subtitles. Only return the translation, no explanation.'},
                    {'role': 'user', 'content': text}
                ],
                'max_tokens': 200,
                'temperature': 0.3
            }).encode()
            req = urllib.request.Request(url, data=payload, headers=headers, method='POST')
            with urllib.request.urlopen(req, timeout=15) as response:
                result = json.loads(response.read().decode())
                if 'choices' in result and len(result['choices']) > 0:
                    translated = result['choices'][0]['message']['content'].strip()
                    TRANSLATION_CACHE[cache_key] = translated
                    return translated
    except Exception as e:
        pass
    
    # 翻译失败，返回空字符串
    return ""


def translate_subtitles(subtitles, batch_size=10):
    """
    批量翻译字幕列表。
    subtitles: [{"start": float, "end": float, "text": "中文"}, ...]
    返回: [{"start": float, "end": float, "text": "中文", "text_en": "English"}, ...]
    """
    result = []
    for sub in subtitles:
        zh_text = sub['text'].strip()
        en_text = translate_text(zh_text)
        result.append({
            'start': sub['start'],
            'end': sub['end'],
            'text': zh_text,
            'text_en': en_text if en_text else zh_text  # 如果翻译失败，使用原文
        })
    return result


# ─── 帧率映射表 ─────────────────────────────────────────────
FPS_MAP = {
    23.976: (24000, "1001/24000s", "2398"),
    23.98:  (24000, "1001/24000s", "2398"),
    24:     (24,    "100/2400s",   "24"),
    25:     (25,    "100/2500s",   "25"),
    29.97:  (30000, "1001/30000s", "2997"),
    30:     (30,    "100/3000s",   "30"),
    50:     (50,    "100/5000s",   "50"),
    59.94:  (60000, "1001/60000s", "5994"),
    60:     (60,    "100/6000s",   "60"),
}

def get_fps_info(fps):
    for key, val in FPS_MAP.items():
        if abs(fps - key) < 0.01:
            return val
    tb = int(round(fps)) * 100
    fd = f"100/{tb}s"
    return (tb, fd, str(int(round(fps))))


def sec_to_ticks(seconds, timebase):
    return int(round(seconds * timebase))


def ticks_str(ticks, timebase):
    if ticks == 0:
        return "0s"
    g = math.gcd(int(ticks), int(timebase))
    n = ticks // g
    d = timebase // g
    if d == 1:
        return f"{n}s"
    return f"{n}/{d}s"


def escape_xml(text):
    text = text.replace('&', '&amp;')
    text = text.replace('<', '&lt;')
    text = text.replace('>', '&gt;')
    text = text.replace('"', '&quot;')
    return text


# ─── 标点清理 ─────────────────────────────────────────────

# 需要去除的标点（逗号、顿号、分号、冒号等）
REMOVE_PUNCTS = r'[，。、；：！？""''（）()【】《》·—…\-\.\,\;\:\!\?\s]'

def clean_punctuation(text):
    """
    清理字幕标点符号：
    - 去除：逗号、句号、顿号、分号、冒号、感叹号、问号、省略号、括号、连字符、空格等
    - 保留：「」引号、《》书名号、·间隔号、—连接号
    - 保留：数字中间的小数点（如 14.09）
    """
    # 先标准化引号：将 "" '' 转为 「」
    text = re.sub(r'\u201c', '「', text)   # " -> 「
    text = re.sub(r'\u201d', '」', text)   # " -> 」
    text = re.sub(r'\u2018', '「', text)   # ' -> 「
    text = re.sub(r'\u2019', '」', text)   # ' -> 」

    # 定义需要移除的字符集
    remove_chars = set(
        '，。、；：！？""''()（）【】…— \t\n\r'
        '.,;:!?\'\"'
    )
    # 排除保留字符
    for ch in '「」《》·—':
        remove_chars.discard(ch)

    result = []
    for i, ch in enumerate(text):
        if ch == '.':
            # 保留数字中间的小数点
            if (i > 0 and text[i-1].isdigit()) and (i + 1 < len(text) and text[i+1].isdigit()):
                result.append(ch)
                continue
            if ch in remove_chars:
                continue
        if ch in remove_chars:
            continue
        result.append(ch)

    return ''.join(result)


# ─── 双语字幕合并 ──────────────────────────────────────────

def merge_bilingual(zh_subtitles, en_subtitles):
    """
    合并中英文字幕为双语字幕列表。
    按 start 时间匹配，未匹配到的用空字符串填充。
    zh/en 格式: [{"start": float, "end": float, "text": str}, ...]
    返回: [{"start": float, "end": float, "text": "中文", "text_en": "English"}, ...]
    """
    # 按 start 排序
    zh_sorted = sorted(zh_subtitles, key=lambda x: x['start'])
    en_sorted = sorted(en_subtitles, key=lambda x: x['start'])

    result = []

    # 简单合并策略：取两者的所有时间点
    all_starts = sorted(set(
        [s['start'] for s in zh_sorted] + [s['start'] for s in en_sorted]
    ))

    zh_idx = 0
    en_idx = 0

    for ts in all_starts:
        # 找最近的中文段
        zh_text = ''
        while zh_idx < len(zh_sorted) and zh_sorted[zh_idx]['start'] <= ts + 0.5:
            zh_text = zh_sorted[zh_idx]['text']
            zh_idx += 1
        if not zh_text and zh_idx > 0:
            zh_text = zh_sorted[zh_idx - 1]['text'] if abs(zh_sorted[zh_idx - 1]['start'] - ts) <= 0.5 else ''

        # 找最近的英文段
        en_text = ''
        while en_idx < len(en_sorted) and en_sorted[en_idx]['start'] <= ts + 0.5:
            en_text = en_sorted[en_idx]['text']
            en_idx += 1
        if not en_text and en_idx > 0:
            en_text = en_sorted[en_idx - 1]['text'] if abs(en_sorted[en_idx - 1]['start'] - ts) <= 0.5 else ''

        # 确定时间范围
        start = ts
        end_candidates = []
        for s in zh_sorted:
            if abs(s['start'] - ts) <= 0.5:
                end_candidates.append(s['end'])
        for s in en_sorted:
            if abs(s['start'] - ts) <= 0.5:
                end_candidates.append(s['end'])
        end = max(end_candidates) if end_candidates else ts + 2.0

        result.append({
            'start': start,
            'end': end,
            'text': zh_text,
            'text_en': en_text
        })

    return result


# ─── FCPXML 生成 ──────────────────────────────────────────

def generate_fcpxml(subtitles, fps=25, output_path=None, source_filename="subtitles",
                    bilingual=False):
    """
    生成符合 FCPXML 1.10 DTD 规范的字幕文件

    参数:
        subtitles: 字幕列表
            单语: [{"start": 0.0, "end": 2.5, "text": "字幕内容"}, ...]
            双语: [{"start": 0.0, "end": 2.5, "text": "中文", "text_en": "English"}, ...]
        fps: 帧率
        output_path: 输出路径
        source_filename: 源文件名
        bilingual: 是否双语模式
    """
    if not subtitles:
        raise ValueError("字幕列表为空")

    fps_f = float(fps)
    timebase, frame_duration_str, fps_name = get_fps_info(fps_f)

    total_secs = max(s["end"] for s in subtitles)
    one_frame_ticks = timebase // int(round(fps_f)) if int(round(fps_f)) > 0 else 1
    total_ticks = sec_to_ticks(total_secs, timebase) + one_frame_ticks

    title_lines = []
    ts_id_counter = [1]

    # 统计翻译状态
    translation_stats = {'total': 0, 'translated': 0, 'failed': 0}
    
    for sub in subtitles:
        text_raw = sub['text'].strip()
        text_en_raw = sub.get('text_en', '').strip() if bilingual else ''
        if not text_raw and not text_en_raw:
            continue

        if bilingual:
            translation_stats['total'] += 1
            # 双语模式：中文在上，英文在下
            # 清理中文标点
            zh_clean = clean_punctuation(text_raw)
            
            # 检查英文翻译是否有效
            if text_en_raw and text_en_raw != text_raw and not text_en_raw.startswith('('):
                # 有效的英文翻译
                en_clean = text_en_raw.strip()
                translation_stats['translated'] += 1
            else:
                # 翻译失败或缺失
                en_clean = "[Translation needed]"
                translation_stats['failed'] += 1
            
            text_display = f"{zh_clean}\n{en_clean}"
            display_name = escape_xml(zh_clean[:20])
        else:
            # 单语模式：直接使用原文（不自动清理标点，标点清理在 skill 流程中处理）
            text_display = text_raw
            display_name = escape_xml(text_raw[:30])

        text = escape_xml(text_display)

        start_ticks = sec_to_ticks(sub['start'], timebase)
        end_ticks = sec_to_ticks(sub['end'], timebase)
        dur_ticks = end_ticks - start_ticks
        if dur_ticks <= 0:
            continue

        offset_str = ticks_str(start_ticks, timebase)
        duration_str = ticks_str(dur_ticks, timebase)
        title_start_str = "0s"

        ts_id = f"ts{ts_id_counter[0]}"
        ts_id_counter[0] += 1

        if bilingual:
            # 双语模式：调整字体大小，中文字体小一些留空间给英文
            font_size = "42"
            font_size_en = "36"
            title_lines.append(
                f'            <title name="{display_name}" lane="1" '
                f'offset="{offset_str}" ref="r2" '
                f'duration="{duration_str}" start="{title_start_str}">\n'
                f'              <param name="Position" key="9999/999166631/999166633/1/100/101" value="0 -300"/>\n'
                f'              <param name="Alignment" key="9999/999166631/999166633/2/354/999169573/401" value="1 (Center)"/>\n'
                f'              <param name="Flatten" key="9999/999166631/999166633/2/351" value="1"/>\n'
                f'              <text>\n'
                f'                <text-style ref="{ts_id}">{text}</text-style>\n'
                f'              </text>\n'
                f'              <text-style-def id="{ts_id}">\n'
                f'                <text-style font="PingFang SC" fontSize="{font_size}" fontFace="Semibold" '
                f'fontColor="1 1 1 1" bold="1" '
                f'shadowColor="0 0 0 0.75" shadowOffset="5 315" alignment="center"/>\n'
                f'              </text-style-def>\n'
                f'            </title>'
            )
        else:
            title_lines.append(
                f'            <title name="{display_name}" lane="1" '
                f'offset="{offset_str}" ref="r2" '
                f'duration="{duration_str}" start="{title_start_str}">\n'
                f'              <param name="Position" key="9999/999166631/999166633/1/100/101" value="0 -450"/>\n'
                f'              <param name="Alignment" key="9999/999166631/999166633/2/354/999169573/401" value="1 (Center)"/>\n'
                f'              <param name="Flatten" key="9999/999166631/999166633/2/351" value="1"/>\n'
                f'              <text>\n'
                f'                <text-style ref="{ts_id}">{text}</text-style>\n'
                f'              </text>\n'
                f'              <text-style-def id="{ts_id}">\n'
                f'                <text-style font="PingFang SC" fontSize="52" fontFace="Semibold" '
                f'fontColor="1 1 1 1" bold="1" '
                f'shadowColor="0 0 0 0.75" shadowOffset="5 315" alignment="center"/>\n'
                f'              </text-style-def>\n'
                f'            </title>'
            )

    titles_xml = "\n".join(title_lines)
    total_str = ticks_str(total_ticks, timebase)

    fcpxml = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE fcpxml>
<fcpxml version="1.10">
  <resources>
    <format id="r1"
            name="FFVideoFormat1920x1080p{fps_name}"
            frameDuration="{frame_duration_str}"
            width="1920"
            height="1080"
            colorSpace="1-1-1 (Rec. 709)"/>
    <effect id="r2"
            name="Basic Title"
            uid=".../Titles.localized/Bumper:Opener.localized/Basic Title.localized/Basic Title.moti"/>
  </resources>
  <library>
    <event name="Subtitles">
      <project name="{escape_xml(source_filename)}_Subtitles">
        <sequence duration="{total_str}" format="r1" tcStart="0s" tcFormat="NDF">
          <spine>
            <gap name="Gap" offset="0s" duration="{total_str}" start="0s">
{titles_xml}
            </gap>
          </spine>
        </sequence>
      </project>
    </event>
  </library>
</fcpxml>'''

    if output_path:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(fcpxml)
        print(f"FCPXML 文件已生成: {output_path}")
    else:
        print(fcpxml)

    return fcpxml


def generate_dual_track_fcpxml(subtitles, fps=25, output_path=None, source_filename="subtitles"):
    """
    生成双轨道双语字幕 FCPXML
    
    参数:
        subtitles: 双轨道字幕列表
            [{"start": 0.0, "end": 2.5, "text": "内容", "lane": 1}, ...]
            lane=1: 中文（上方）
            lane=2: 英文（下方）
        fps: 帧率
        output_path: 输出路径
        source_filename: 源文件名
    """
    if not subtitles:
        raise ValueError("字幕列表为空")

    fps_f = float(fps)
    timebase, frame_duration_str, fps_name = get_fps_info(fps_f)

    total_secs = max(s["end"] for s in subtitles)
    one_frame_ticks = timebase // int(round(fps_f)) if int(round(fps_f)) > 0 else 1
    total_ticks = sec_to_ticks(total_secs, timebase) + one_frame_ticks

    title_lines = []
    ts_id_counter = [1]

    for sub in subtitles:
        text_raw = sub['text'].strip()
        lane = sub.get('lane', 1)
        if not text_raw:
            continue

        text = escape_xml(text_raw)
        display_name = escape_xml(text_raw[:20])

        start_ticks = sec_to_ticks(sub['start'], timebase)
        end_ticks = sec_to_ticks(sub['end'], timebase)
        dur_ticks = end_ticks - start_ticks
        if dur_ticks <= 0:
            continue

        offset_str = ticks_str(start_ticks, timebase)
        duration_str = ticks_str(dur_ticks, timebase)
        title_start_str = "0s"

        ts_id = f"ts{ts_id_counter[0]}"
        ts_id_counter[0] += 1

        # 根据轨道设置位置和字号
        # FCP Position 坐标系：Y负值向下，绝对值越大越靠画面底部
        # Lane 1 (中文): 位置 -300 (上方，离中心近), 字号 44
        # Lane 2 (英文): 位置 -420 (下方，离中心远), 字号 38
        if lane == 1:
            position = "0 -300"  # 中文在上
            font_size = "44"  # 中文稍大
        else:
            position = "0 -420"  # 英文在下
            font_size = "38"  # 英文稍小

        title_lines.append(
            f'            <title name="{display_name}" lane="{lane}" '
            f'offset="{offset_str}" ref="r2" '
            f'duration="{duration_str}" start="{title_start_str}">\n'
            f'              <param name="Position" key="9999/999166631/999166633/1/100/101" value="{position}"/>\n'
            f'              <param name="Alignment" key="9999/999166631/999166633/2/354/999169573/401" value="1 (Center)"/>\n'
            f'              <param name="Flatten" key="9999/999166631/999166633/2/351" value="1"/>\n'
            f'              <text>\n'
            f'                <text-style ref="{ts_id}">{text}</text-style>\n'
            f'              </text>\n'
            f'              <text-style-def id="{ts_id}">\n'
            f'                <text-style font="PingFang SC" fontSize="{font_size}" fontFace="Semibold" '
                f'fontColor="1 1 1 1" bold="1" '
                f'shadowColor="0 0 0 0.75" shadowOffset="5 315" alignment="center"/>\n'
            f'              </text-style-def>\n'
            f'            </title>'
        )

    titles_xml = "\n".join(title_lines)
    total_str = ticks_str(total_ticks, timebase)

    fcpxml = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE fcpxml>
<fcpxml version="1.10">
  <resources>
    <format id="r1"
            name="FFVideoFormat1920x1080p{fps_name}"
            frameDuration="{frame_duration_str}"
            width="1920"
            height="1080"
            colorSpace="1-1-1 (Rec. 709)"/>
    <effect id="r2"
            name="Basic Title"
            uid=".../Titles.localized/Bumper:Opener.localized/Basic Title.localized/Basic Title.moti"/>
  </resources>
  <library>
    <event name="Subtitles">
      <project name="{escape_xml(source_filename)}_Subtitles">
        <sequence duration="{total_str}" format="r1" tcStart="0s" tcFormat="NDF">
          <spine>
            <gap name="Gap" offset="0s" duration="{total_str}" start="0s">
{titles_xml}
            </gap>
          </spine>
        </sequence>
      </project>
    </event>
  </library>
</fcpxml>'''

    if output_path:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(fcpxml)
        print(f"FCPXML 文件已生成: {output_path}")
    else:
        print(fcpxml)

    return fcpxml


def main():
    """命令行入口
    用法:
        generate_fcpxml.py <subtitles_json> <fps> [output_path] [source_filename] [--bilingual]

    subtitles_json 格式:
        单语: [{"start": 0.0, "end": 2.5, "text": "字幕内容"}, ...]
        双语: [{"start": 0.0, "end": 2.5, "text": "中文", "text_en": "English"}, ...]
        或
        {"subtitles": [...]}
    """
    if len(sys.argv) < 3:
        print("Usage: generate_fcpxml.py <subtitles_json> <fps> [output_path] [source_filename] [--bilingual]")
        print('Example: generate_fcpxml.py \'[{"start":0,"end":2,"text":"Hello"}]\' 25 output.fcpxml')
        sys.exit(1)

    subtitles_data = json.loads(sys.argv[1])
    fps = float(sys.argv[2])
    output_path = sys.argv[3] if len(sys.argv) > 3 else None
    source_filename = sys.argv[4] if len(sys.argv) > 4 else "subtitles"
    bilingual = '--bilingual' in sys.argv

    if isinstance(subtitles_data, dict):
        subtitles = subtitles_data.get('subtitles', [])
    else:
        subtitles = subtitles_data

    generate_fcpxml(subtitles, fps, output_path, source_filename, bilingual=bilingual)


if __name__ == '__main__':
    main()
