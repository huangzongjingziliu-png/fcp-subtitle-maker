---
name: fcp-subtitle-maker
description: 将音频或视频转换为Final Cut Pro的.fcpxml字幕文件。支持SRT直接导入、智能断句（顿号/空格自动拆分）、时间延迟补偿、自动帧率识别、中英双语字幕（中英独立轨道）。默认使用平方-简字体。
---

# FCP Subtitle Maker

将音频或视频文件直接转换为 Final Cut Pro 可导入的 .fcpxml 字幕文件。

## v1.6.0 更新

### 🎯 新增功能

**1. 智能断句**
- 自动在顿号（、）、空格、句号（。！？）等标点处拆分长字幕
- 默认单条字幕不超过 18 个字符，可自定义
- 按字符比例智能分配时间

**2. 时间延迟补偿**
- 解决字幕提前出现的问题
- 通过 `--delay` 参数调整，让字幕延后出现
- 默认延迟 0 秒，建议尝试 0.2-0.5 秒

### 断句优先级
1. 句末标点（。！？）— 最优先断点
2. 分号（；）
3. 逗号（，）
4. **顿号（、）** — 用户特别关注！
5. 空格
6. 冒号（：）

## 核心原则

1. **字幕断句完全尊重用户输入** — 用户提供 SRT 则用 SRT 断句，提供文字稿则智能断句
2. **默认使用平方-简（PingFang SC）字体** — 可在 FCP 中批量修改
3. **时间轴精确** — 使用 Whisper 语音识别获取精确时间轴，禁止等分时长
4. **双轨道独立** — 中英文各占一个轨道，可单独开关、调整

## 使用场景

### 场景1：SRT 直接转 FCPXML（最常用，推荐）
- 输入：SRT 字幕文件（用户已在剪映等工具中断好句）
- 输出：可直接导入 FCP 的 .fcpxml 字幕文件
- **优势**：完全保留用户的断句和时间轴，零损失

**命令示例**：
```bash
# 基本用法
python3 generate_fcpxml.py --srt input.srt 25 output.fcpxml source_name

# 添加时间延迟补偿（解决字幕提前问题）
python3 generate_fcpxml.py --srt input.srt 25 output.fcpxml source_name --delay 0.3

# 双语 SRT（中文+英文）
python3 generate_fcpxml.py --srt cn.srt --srt-en en.srt 25 output.fcpxml source_name
```

### 场景2：音频/视频 + 文字稿 → 双语字幕
- 输入：音频/视频 + 中文文字稿 +（可选）英文翻译稿
- 输出：双轨道双语字幕（中英独立轨道）

### 场景3：音频/视频 → 单语字幕
- 输入：音频/视频 + 文字稿
- 输出：单轨道字幕

## 执行流程

### 场景1：SRT 直接转 FCPXML

```
用户提供 SRT 文件 → 解析 SRT 时间轴和文本 → （可选）智能断句 → 生成 FCPXML
```

**步骤**：
1. 确认帧率（默认 25fps）
2. 解析 SRT 文件，直接使用其断句和时间轴
3. 如有英文 SRT，按时间对齐合并为双语
4. （可选）启用智能断句拆分长字幕
5. （可选）添加时间延迟补偿
6. 调用 `generate_fcpxml.py --srt` 生成 FCPXML

### 场景2和3：音频/视频 + 文字稿

#### 1. 确认帧率
- 视频文件：自动识别，向用户确认
- 音频文件：询问用户，默认 25fps

#### 2. 语音识别获取精确时间轴（强制步骤）

**⚠️ 这是必须步骤，不可跳过！禁止简单按等分时长分配字幕时间。**

**识别方法（按优先级）**：
1. **平台自带功能**（`audios_understand`）：可直接返回带时间戳的识别结果
2. **本地 whisper**：使用 openai-whisper 命令行工具
3. **在线 API**：提示用户安装或使用

**Whisper 命令示例**：
```bash
# 提取音频（如源文件是视频）
ffmpeg -i input.mp4 -vn -acodec pcm_s16le -ar 16000 -ac 1 output.wav

# 运行 whisper（获取逐句时间戳）
whisper output.wav --model medium --language zh --output_format srt --output_dir ./whisper_output
```

**关键原则**：
- **必须**使用语音识别获取每一句的精确 start/end 时间
- **禁止**按总时长等分分配时间
- **禁止**使用固定间隔
- 识别结果只用于**时间轴对齐**，**不用于字幕内容**
- 字幕内容严格使用用户提供的文字稿

#### 3. 文字稿与时间轴对齐 + 智能断句

**核心原则：尊重用户文字稿的原始断句，配合智能断句优化！**

如果用户的文字稿是分段落/分行写的，每一行就是一条字幕。如果单行过长，会自动在标点处拆分。

**对齐方法**：
1. 用户文字稿按行/段落拆分（一行 = 一条字幕）
2. 将每段与 Whisper segments 按内容匹配
3. 匹配规则：
   - 逐个 Whisper segment 检查，累积文字直到覆盖一个完整段
   - 该段的 start = 第一个匹配 segment 的 start
   - 该段的 end = 最后一个匹配 segment 的 end
4. **智能断句**：如果单条字幕超过 max_chars（默认18），自动在标点处拆分

**⚠️ 禁止做法**：
- ❌ `start = i * (total_duration / num_segments)` — 等分时间
- ❌ `duration = 3.0` — 固定每句3秒
- ❌ 忽略语音识别结果，凭感觉分配时间

**标点清理**（切分后执行，可选）：
- 去除：，。、；：！？""''（）空格
- 保留：「」《》·—
- 转换：""→「」 ''→「」

#### 4. 双语字幕（可选）

**用户提供英文稿时**：
- 读取英文文稿
- 段落数对齐：等于中文 → 一一对应；少于中文 → AI精简翻译补充

**未提供英文稿时**：
- AI 逐段分析中文语义
- 精简翻译为英文（每段 60-100 字符）

#### 5. 生成 FCPXML

调用脚本：`generate_fcpxml.py`

**输出参数**：

| 项目 | 中文 | 英文 |
|------|------|------|
| Lane | 1 | 2 |
| 字体 | 平方-简（PingFang SC） | 平方-简（PingFang SC） |
| 字号（双语） | 44 | 38 |
| 字号（单语） | 52 | - |
| Position | `0 -300`（上方） | `0 -420`（下方） |
| 字色 | 白色 `1 1 1 1` | 白色 `1 1 1 1` |
| 对齐 | 居中 | 居中 |

## 命令行参数

### 基本参数
```bash
python3 generate_fcpxml.py <subtitles_json> <fps> [output_path] [source_filename]
python3 generate_fcpxml.py --srt <srt_path> <fps> [output_path] [source_filename]
```

### 新增参数（v1.6.0）

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--delay N` | 时间延迟补偿（秒），解决字幕提前出现的问题 | 0.0 |
| `--max-chars N` | 单条字幕最大字符数，超过则智能断句 | 18 |
| `--no-split` | 禁用智能断句 | - |

### 参数示例

```bash
# 基本用法
python3 generate_fcpxml.py --srt input.srt 25 output.fcpxml source

# 字幕提前0.5秒？添加延迟补偿
python3 generate_fcpxml.py --srt input.srt 25 output.fcpxml source --delay 0.5

# 单条字幕最多15个字
python3 generate_fcpxml.py --srt input.srt 25 output.fcpxml source --max-chars 15

# 禁用智能断句（保持原始断句）
python3 generate_fcpxml.py --srt input.srt 25 output.fcpxml source --no-split
```

## 依赖项

| 工具 | 必需 | 说明 |
|------|------|------|
| ffmpeg | 是 | 音频提取和格式转换 |
| whisper | 场景2/3 | 语音识别获取时间轴 |
| SRT 文件 | 场景1 | 用户提供的断好句的字幕 |

## 触发条件

- "生成 fcp 字幕"
- "音频/视频转字幕"
- "给我加上字幕"
- "双语字幕"
- "SRT 转 FCPXML"
- "把 SRT 导入 FCP"
- 上传音频/视频 + 文字稿
- 上传 SRT 文件

## 注意事项

1. **SRT 是最佳输入** — 如果用户已有 SRT 文件（比如从剪映导出），直接用 SRT 模式，最准确
2. **智能断句默认开启** — 会在顿号、空格、句号等处自动拆分长字幕
3. **时间延迟补偿** — 如果字幕提前出现，使用 `--delay` 参数调整（建议 0.2-0.5 秒）
4. **默认字体平方-简** — 生成后可在 FCP 中选中所有字幕批量修改字体
5. **text-style 属性严格合规** — 不使用 bold/fontFace/shadowColor/shadowOffset，避免 DTD 验证失败
6. **双轨道独立** — 中文 Lane 1、英文 Lane 2，可分别开关和调整
7. **中文在上、英文在下** — 中文 position=`0 -300`，英文 position=`0 -420`

## 版本历史

### v1.6.0 (2026-04-12)
- ✨ 新增智能断句功能，自动在顿号/空格/句号处拆分长字幕
- ✨ 新增时间延迟补偿参数 `--delay`，解决字幕提前出现的问题
- ✨ 新增 `--max-chars` 参数，控制单条字幕最大字符数
- ✨ 新增 `--no-split` 参数，可禁用智能断句
- 🐛 修复长字幕不会断开的问题
- 🐛 修复字幕时间提前的问题

### v1.5.0
- 支持 SRT 直接导入
- 双语字幕支持
