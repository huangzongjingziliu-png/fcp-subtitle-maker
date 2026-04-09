#!/usr/bin/env python3
"""
FCPXML Subtitle Generator - Final Cut Pro X 10.4+ Compatible
生成符合 FCPXML DTD 规范的字幕文件

功能：
- SRT 直接导入：使用 SRT 自带的断句和时间轴（核心功能）
- 双语字幕支持：中英文独立轨道，中文在上、英文在下
- 默认字体：平方-简（PingFang SC）
- 严格 DTD 合规：不使用 bold/fontFace/shadowColor/shadowOffset 等可能导致验证失败的属性

重要原则：
- 如果用户提供了 SRT 文件，直接使用 SRT 的断句和时间轴，不做二次切分
- 字幕断句完全尊重用户的原始输入（SRT 或文字稿的切分）
- 默认字体为 PingFang SC（平方-简），可在 FCP 中批量修改

版本: v2.0.0
"""

import json
import sys
import math
import re
import os
from fractions import Fraction


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
    """根据帧率获取 timebase、frameDuration 字符串和 fps 名称"""
    for key, val in FPS_MAP.items():
        if abs(fps - key) < 0.01:
            return val
    tb = int(round(fps)) * 100
    fd = f"100/{tb}s"
    return (tb, fd, str(int(round(fps))))


def sec_to_ticks(seconds, timebase):
    """秒数转为 ticks"""
    return int(round(seconds * timebase))


def ticks_str(ticks, timebase):
    """ticks 转为 FCPXML 时间字符串（最简分数形式）"""
    if ticks == 0:
        return "0s"
    g = math.gcd(int(ticks), int(timebase))
    n = ticks // g
    d = timebase // g
    if d == 1:
        return f"{n}s"
    return f"{n}/{d}s"


def escape_xml(text):
    """转义 XML 特殊字符"""
    text = text.replace('&', '&amp;')
    text = text.replace('<', '&lt;')
    text = text.replace('>', '&gt;')
    text = text.replace('"', '&quot;')
    return text


# ─── SRT 解析 ─────────────────────────────────────────────

def parse_srt(srt_path):
    """
    解析 SRT 字幕文件，返回带精确时间戳的字幕列表。
    
    SRT 格式示例：
    1
    00:00:15,000 --> 00:00:19,760
    巍巍贺兰山横亘西北大地
    
    返回: [{"start": 15.0, "end": 19.76, "text": "巍巍贺兰山横亘西北大地"}, ...]
    """
    subtitles = []
    
    with open(srt_path, 'r', encoding='utf-8-sig') as f:
        content = f.read()
    
    # 按空行分割
    blocks = re.split(r'\n\s*\n', content.strip())
    
    for block in blocks:
        lines = block.strip().split('\n')
        if len(lines) < 3:
            continue
        
        # 跳过序号行，找时间行
        time_line_idx = -1
        for i, line in enumerate(lines):
            if '-->' in line:
                time_line_idx = i
                break
        
        if time_line_idx < 0:
            continue
        
        # 解析时间
        time_line = lines[time_line_idx]
        time_match = re.match(
            r'(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)',
            time_line.strip()
        )
        if not time_match:
            continue
        
        g = time_match.groups()
        start = int(g[0]) * 3600 + int(g[1]) * 60 + int(g[2]) + int(g[3]) / 1000.0
        end = int(g[4]) * 3600 + int(g[5]) * 60 + int(g[6]) + int(g[7]) / 1000.0
        
        # 字幕文本（可能有多行）
        text_lines = lines[time_line_idx + 1:]
        text = '\n'.join(text_lines).strip()
        
        if text and start < end:
            subtitles.append({
                'start': start,
                'end': end,
                'text': text
            })
    
    return subtitles


def parse_srt_dual(srt_cn_path, srt_en_path=None):
    """
    解析双 SRT 文件（中文和英文），返回双轨道字幕列表。
    
    如果只提供一个 SRT 文件，返回单语字幕（中文）。
    如果提供两个 SRT 文件，按时间对齐合并为双语字幕。
    
    返回: [
        {"start": float, "end": float, "text": "中文", "text_en": "English"},
        ...
    ]
    """
    cn_subs = parse_srt(srt_cn_path)
    
    if not srt_en_path or not os.path.exists(srt_en_path):
        # 单语模式，返回中文
        return [{"start": s['start'], "end": s['end'], "text": s['text'], "text_en": ""} for s in cn_subs]
    
    en_subs = parse_srt(srt_en_path)
    
    # 按时间对齐：以中文字幕为主，找时间最近的英文字幕
    result = []
    for cn in cn_subs:
        en_text = ""
        best_overlap = 0
        
        for en in en_subs:
            # 计算时间重叠
            overlap_start = max(cn['start'], en['start'])
            overlap_end = min(cn['end'], en['end'])
            overlap = overlap_end - overlap_start
            
            if overlap > best_overlap:
                best_overlap = overlap
                en_text = en['text']
        
        result.append({
            'start': cn['start'],
            'end': cn['end'],
            'text': cn['text'],
            'text_en': en_text
        })
    
    return result


# ─── 标点清理 ─────────────────────────────────────────────

def clean_punctuation(text):
    """
    清理字幕标点符号：
    - 去除：逗号、句号、顿号、分号、冒号、感叹号、问号、省略号、括号等
    - 保留：「」引号、《》书名号、·间隔号、—连接号
    - 保留：数字中间的小数点（如 14.09）
    """
    # 标准化引号
    text = re.sub(r'\u201c', '「', text)   # " -> 「
    text = re.sub(r'\u201d', '」', text)   # " -> 」
    text = re.sub(r'\u2018', '「', text)   # ' -> 「
    text = re.sub(r'\u2019', '」', text)   # ' -> 」
    
    # 需要移除的字符
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


# ─── FCPXML 生成 ──────────────────────────────────────────

def _build_title(lane, offset_str, duration_str, display_name, text,
                 ts_id, font, font_size, position):
    """
    生成单个 <title> 元素的 XML 字符串。
    
    严格合规：不使用 bold、fontFace、shadowColor、shadowOffset 属性。
    字体和样式可在 FCP 中批量调整。
    """
    return (
        f'            <title name="{display_name}" lane="{lane}" '
        f'offset="{offset_str}" ref="r2" '
        f'duration="{duration_str}" start="0s">\n'
        f'              <param name="Position" key="9999/999166631/999166633/1/100/101" value="{position}"/>\n'
        f'              <param name="Alignment" key="9999/999166631/999166633/2/354/999169573/401" value="1 (Center)"/>\n'
        f'              <param name="Flatten" key="9999/999166631/999166633/2/351" value="1"/>\n'
        f'              <text>\n'
        f'                <text-style ref="{ts_id}">{text}</text-style>\n'
        f'              </text>\n'
        f'              <text-style-def id="{ts_id}">\n'
        f'                <text-style font="{font}" fontSize="{font_size}" '
        f'fontColor="1 1 1 1" alignment="center"/>\n'
        f'              </text-style-def>\n'
        f'            </title>'
    )


def generate_fcpxml(subtitles, fps=25, output_path=None, source_filename="subtitles",
                    bilingual=False, font_cn="PingFang SC", font_en="PingFang SC",
                    clean_punct=True):
    """
    生成符合 FCPXML 1.10 DTD 规范的双轨道字幕文件。
    
    ⚠️ 重要：字幕的断句和时间轴完全由 subtitles 参数决定。
    如果 subtitles 来自 SRT 解析，则直接使用 SRT 的断句，不做二次切分。
    
    参数:
        subtitles: 字幕列表
            单语: [{"start": 0.0, "end": 2.5, "text": "字幕内容"}, ...]
            双语: [{"start": 0.0, "end": 2.5, "text": "中文", "text_en": "English"}, ...]
        fps: 帧率
        output_path: 输出路径
        source_filename: 源文件名（用于项目名称）
        bilingual: 是否双语模式
        font_cn: 中文字体（默认 PingFang SC / 平方-简）
        font_en: 英文字体（默认 PingFang SC / 平方-简）
        clean_punct: 是否清理标点（默认 True）
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
    
    # 双语模式的字体大小
    CN_FONT_SIZE_DUAL = "44"   # 双语时中文
    EN_FONT_SIZE_DUAL = "38"   # 双语时英文
    # 单语模式的字体大小
    CN_FONT_SIZE_SINGLE = "52"  # 单语中文
    
    # 位置
    CN_POSITION = "0 -300"   # 中文在上
    EN_POSITION = "0 -420"   # 英文在下
    SINGLE_POSITION = "0 -450"  # 单语位置

    for sub in subtitles:
        text_raw = sub['text'].strip()
        text_en_raw = sub.get('text_en', '').strip() if bilingual else ''
        
        if not text_raw and not text_en_raw:
            continue

        # 处理中文文本
        if text_raw:
            zh_clean = clean_punctuation(text_raw) if clean_punct else text_raw
        else:
            zh_clean = ""
        
        # 处理英文文本
        if bilingual and text_en_raw:
            en_clean = text_en_raw
        else:
            en_clean = ""

        start_ticks = sec_to_ticks(sub['start'], timebase)
        end_ticks = sec_to_ticks(sub['end'], timebase)
        dur_ticks = end_ticks - start_ticks
        if dur_ticks <= 0:
            continue

        offset_str = ticks_str(start_ticks, timebase)
        duration_str = ticks_str(dur_ticks, timebase)

        if bilingual:
            # 双语模式：生成两个独立 title（中文 lane=1，英文 lane=2）
            
            # 中文字幕
            if zh_clean:
                ts_id = f"ts{ts_id_counter[0]}"
                ts_id_counter[0] += 1
                cn_name = escape_xml(zh_clean[:20])
                cn_text = escape_xml(zh_clean)
                title_lines.append(
                    _build_title(
                        lane=1, offset_str=offset_str, duration_str=duration_str,
                        display_name=cn_name, text=cn_text, ts_id=ts_id,
                        font=font_cn, font_size=CN_FONT_SIZE_DUAL, position=CN_POSITION
                    )
                )
            
            # 英文字幕
            if en_clean:
                ts_id = f"ts{ts_id_counter[0]}"
                ts_id_counter[0] += 1
                en_name = escape_xml(en_clean[:20])
                en_text = escape_xml(en_clean)
                title_lines.append(
                    _build_title(
                        lane=2, offset_str=offset_str, duration_str=duration_str,
                        display_name=en_name, text=en_text, ts_id=ts_id,
                        font=font_en, font_size=EN_FONT_SIZE_DUAL, position=EN_POSITION
                    )
                )
        else:
            # 单语模式
            if zh_clean:
                ts_id = f"ts{ts_id_counter[0]}"
                ts_id_counter[0] += 1
                cn_name = escape_xml(zh_clean[:30])
                cn_text = escape_xml(zh_clean)
                title_lines.append(
                    _build_title(
                        lane=1, offset_str=offset_str, duration_str=duration_str,
                        display_name=cn_name, text=cn_text, ts_id=ts_id,
                        font=font_cn, font_size=CN_FONT_SIZE_SINGLE, position=SINGLE_POSITION
                    )
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
        print(f"  字幕条数: {len(title_lines)}")
        if bilingual:
            cn_count = sum(1 for l in title_lines if 'lane="1"' in l)
            en_count = sum(1 for l in title_lines if 'lane="2"' in l)
            print(f"  中文: {cn_count} 条, 英文: {en_count} 条")
        print(f"  帧率: {fps}fps")
        print(f"  字体: 中文={font_cn}, 英文={font_en}")
    else:
        print(fcpxml)

    return fcpxml


# ─── 命令行入口 ──────────────────────────────────────────

def main():
    """
    命令行入口
    
    用法:
        # 从 JSON 生成
        generate_fcpxml.py <subtitles_json> <fps> [output_path] [source_filename] [--bilingual]
        
        # 从 SRT 生成（单语）
        generate_fcpxml.py --srt <srt_path> <fps> [output_path] [source_filename]
        
        # 从 SRT 生成（双语，中文+英文 SRT）
        generate_fcpxml.py --srt <cn_srt_path> --srt-en <en_srt_path> <fps> [output_path] [source_filename]

    subtitles_json 格式:
        单语: [{"start": 0.0, "end": 2.5, "text": "字幕内容"}, ...]
        双语: [{"start": 0.0, "end": 2.5, "text": "中文", "text_en": "English"}, ...]
    """
    args_list = sys.argv[1:]
    
    # 检查是否使用 SRT 模式
    srt_path = None
    srt_en_path = None
    
    if '--srt' in args_list:
        idx = args_list.index('--srt')
        srt_path = args_list[idx + 1]
        args_list = args_list[:idx] + args_list[idx + 2:]
    
    if '--srt-en' in args_list:
        idx = args_list.index('--srt-en')
        srt_en_path = args_list[idx + 1]
        args_list = args_list[:idx] + args_list[idx + 2:]
    
    bilingual = '--bilingual' in args_list
    no_clean = '--no-clean' in args_list
    
    if srt_path:
        # SRT 模式
        subtitles = parse_srt_dual(srt_path, srt_en_path)
        if srt_en_path:
            bilingual = True
        fps = float(args_list[0]) if args_list else 25.0
        output_path = args_list[1] if len(args_list) > 1 else None
        source_filename = args_list[2] if len(args_list) > 2 else os.path.splitext(os.path.basename(srt_path))[0]
    else:
        # JSON 模式
        if len(args_list) < 2:
            print("Usage:")
            print("  generate_fcpxml.py <subtitles_json> <fps> [output_path] [source_filename] [--bilingual]")
            print("  generate_fcpxml.py --srt <srt_path> <fps> [output_path] [source_filename]")
            print("  generate_fcpxml.py --srt <cn_srt> --srt-en <en_srt> <fps> [output_path] [source_filename]")
            sys.exit(1)
        
        subtitles_data = json.loads(args_list[0])
        fps = float(args_list[1])
        output_path = args_list[2] if len(args_list) > 2 else None
        source_filename = args_list[3] if len(args_list) > 3 else "subtitles"
        
        if isinstance(subtitles_data, dict):
            subtitles = subtitles_data.get('subtitles', [])
        else:
            subtitles = subtitles_data

    generate_fcpxml(
        subtitles, fps, output_path, source_filename,
        bilingual=bilingual,
        clean_punct=not no_clean
    )


if __name__ == '__main__':
    main()
