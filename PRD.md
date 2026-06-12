# redbook-pipeline 产品需求文档 (PRD)

> **版本**: v1.0 | **日期**: 2026-06-09 | **状态**: 待确认

---

## 1. 项目概述

**redbook-pipeline** 是一个自动化"论文介绍视频"生成系统。输入一篇学术论文 PDF，系统自动分析论文内容，生成 PPT 演示文稿，并合成带 TTS 旁白讲解的视频。

### 1.1 核心目标

- **输入**: 学术论文 PDF 文件
- **处理**: AI 自动分析 → 结构化摘要 → 生成 PPT 内容 + 旁白脚本
- **输出**: 带克隆声音旁白的 PPT 讲解视频（MP4）

### 1.2 关键资源确认

| 资源 | 位置 | 说明 |
|------|------|------|
| PPT 模版 | `pptx_template/模板.pptx` | 16 页固定风格，仅覆盖部分填充 |
| 声音样本 | `source_voice/source.mp3` | 用于火山引擎音色克隆 |
| 火山引擎 API | `apis.txt` | appid + apikey（TTS + 克隆共用） |
| Kimi API | `apis.txt` | 用于 LLM 内容生成 |
| 官方示例 | `volc_examples/` | voice_sym.command（v3 标准 TTS）+ voice_clone.command（v1 克隆 TTS） |

---

## 2. 整体 Pipeline 流程（7 步）

```
Step 0: 初始化工作空间 (Job ID + 输出目录)
    ↓
Step 1: PDF 解析 ──────→ 01_raw_text.json（结构化文本）
    ↓
Step 2: LLM 论文分析 ──→ 02_paper_structure.json（论文摘要）
    ↓
Step 3: LLM 幻灯片生成 → 03_slide_content.json（内容 + 旁白脚本）
    ↓
    ├───────────────────────┐
    │                       │
Step 4: PPT 填充          Step 5: TTS 合成（含克隆 + 语音合成）
    ↓                       ↓
06_output.pptx        05_audio/slide_*.mp3
    ↓
Step 6: PPT 渲染 ──────→ 07_frames/slide_*.png
    ↓
Step 7: 视频合成 ──────→ 08_final.mp4 ★
```

### 2.1 Step 5 详细拆分

```
Step 5a: 音色克隆（首次运行）
  输入: source_voice/source.mp3
  输出: speaker_id（voice_type）
  流程:
    1. POST /api/v1/mega_tts/audio/upload 上传音频
    2. POST /api/v1/mega_tts/train/submit 提交训练
    3. 轮询 GET /api/v1/mega_tts/status 查询训练状态
    4. 训练完成获取 speaker_id
  注: speaker_id 持久化保存，后续运行直接复用

Step 5b: TTS 语音合成（每次运行）
  输入: 03_slide_content.json 中每张 slide 的 narration_script
  输出: 05_audio/slide_*.mp3
  API: POST https://openspeech.bytedance.com/api/v1/tts
  参数:
    - x-api-key: {apis.txt 中的 apikey}
    - app.cluster: "volcano_icl"
    - audio.voice_type: {speaker_id（克隆音色）}
    - audio.encoding: "mp3"
    - audio.speed_ratio: 1.0
    - request.text: {narration_script}
    - request.operation: "query"
```

---

## 3. PPT 模版结构分析

### 3.1 模版基本信息

- **总页数**: 16 页
- **尺寸**: 25.0cm × 14.0cm（≈ 16:9）

### 3.2 各页结构与可填充区域

| 页码 | 类型 | 固定内容 | 需动态填充的文本框 |
|------|------|---------|-------------------|
| **Slide 1** | 封面 | 背景装饰、Logo 图片 | `矩形 3`(英文题目)、`矩形 1`(中文题目)、`TextBox 12`(汇报人信息) |
| **Slide 2** | 目录 | 标题"目录" | `内容占位符 2`(目录条目列表) |
| **Slide 3** | 文献介绍 | 装饰矩形、Logo | `TextBox 8`(标题-文献介绍)、`TextBox 12`(期刊/分区/影响因子/作者/单位) |
| **Slide 4** | 研究背景 | 装饰矩形、Logo | `TextBox 8`(标题-研究背景) + **需新增内容文本框** |
| **Slide 5** | 研究目的 | 装饰矩形、Logo | `TextBox 8`(标题-研究目的) + **需新增内容文本框** |
| **Slide 6-9** | 文章结果(×4) | 装饰矩形、Logo | `TextBox 8`(标题-文章结果：) + **需新增内容文本框** |
| **Slide 10-13** | 研究方法(×4) | 装饰矩形、Logo | `TextBox 8`(标题-文章思路-主要研究方法) + **需新增内容文本框** |
| **Slide 14-15** | 讨论(×2) | 装饰矩形、Logo | `TextBox 8`(标题-讨论) + **需新增内容文本框** |
| **Slide 16** | 结束页 | 背景装饰、感谢文字 | `圆角矩形 11`(可填补充信息) |

### 3.3 内容填充策略

**Slide 4~15 的内容区目前是空白的，没有预设文本框。** 填充方式：

```python
# 代码逻辑：在标题下方动态添加文本框
for slide in content_slides:
    # 找到标题 TextBox 的位置和尺寸
    title_shape = find_shape_by_name(slide, "TextBox 8")
    # 在标题下方创建新文本框，填充 bullet_points 内容
    content_left = Cm(1.5)
    content_top = title_shape.top + title_shape.height + Cm(0.5)
    content_width = Cm(22.0)
    content_height = Cm(10.0)
    add_text_box(slide, left, top, width, height, content_text)
```

### 3.4 动态页数策略

LLM 根据内容量决定实际使用的页面数量，**多余页面自动删除**。例如：
- 若论文结果不多，只需 2 页结果 → 删除 Slide 8-9
- 若研究方法只需 2 页 → 删除 Slide 12-13
- 最终 PPT 页数 = 实际内容所需页数（最少保留每类至少 1 页）

---

## 4. 核心模块设计

### 4.1 BaseSkill（所有 Skill 的基类）

```python
class BaseSkill(ABC):
    """所有 Skill 的基类，提供统一接口、断点续跑、结果持久化"""

    @abstractmethod
    def skill_name(self) -> str: ...

    @abstractmethod
    def output_path(self) -> Path: ...

    @abstractmethod
    def execute(self, **inputs) -> Any: ...

    def is_done(self) -> bool:
        """检查 .done 标记文件，支持断点续跑"""

    def run(self, force: bool = False, **inputs) -> Any:
        """统一入口：检查断点 → 执行 → 持久化 → 标记 .done"""
```

### 4.2 各 Skill 详细设计

#### Skill 1: PDFParserSkill

| 属性 | 内容 |
|------|------|
| 职责 | 从 PDF 提取结构化文本，识别标题、摘要、章节、图表 caption |
| 输入 | `*.pdf` 文件路径 |
| 输出 | `01_raw_text.json` |
| 核心库 | `PyMuPDF (fitz)` |
| 输出格式 | 见 5.1 节 |

#### Skill 2: PaperAnalyzerSkill

| 属性 | 内容 |
|------|------|
| 职责 | LLM 分析论文，提取核心要素（背景、问题、方法、结果、结论） |
| 输入 | `01_raw_text.json` |
| 输出 | `02_paper_structure.json` |
| LLM | Kimi（moonshot-v1-8k） |
| 输出格式 | 见 5.2 节 |

#### Skill 3: SlideGeneratorSkill

| 属性 | 内容 |
|------|------|
| 职责 | LLM 生成每张幻灯片的标题、要点、旁白脚本，决定实际页数 |
| 输入 | `02_paper_structure.json` + 模版页数约束 |
| 输出 | `03_slide_content.json` |
| LLM | Kimi（moonshot-v1-8k） |
| 关键要求 | narration_script 必须是**口语化中文**，适合视频讲解 |
| 输出格式 | 见 5.3 节 |

#### Skill 4: PPTBuilderSkill

| 属性 | 内容 |
|------|------|
| 职责 | 读取 `pptx_template/模板.pptx`，按内容填充，删除多余页 |
| 输入 | `03_slide_content.json` + `assets/template.pptx` |
| 输出 | `06_output.pptx` |
| 核心库 | `python-pptx` |
| 填充规则 | ① 固定区域按名称匹配填充 ② 内容区动态添加文本框 ③ 删除未使用的幻灯片 |

#### Skill 5a: VoiceCloneSkill（首次运行）

| 属性 | 内容 |
|------|------|
| 职责 | 上传声音样本，训练克隆音色，获取 speaker_id |
| 输入 | `source_voice/source.mp3` |
| 输出 | `voice_clone_result.json`（含 speaker_id） |
| API | 火山引擎 Mega-TTS 音色复刻 |
| 认证 | x-api-key: `9a33f333-25a1-4236-b0a4-592c44ccb417` |

#### Skill 5b: TTSSynthesizerSkill

| 属性 | 内容 |
|------|------|
| 职责 | 逐张幻灯片旁白 → TTS → MP3 |
| 输入 | `03_slide_content.json` 中各 slide 的 `narration_script` |
| 输出 | `05_audio/slide_*.mp3` |
| API | POST `https://openspeech.bytedance.com/api/v1/tts` |
| 请求头 | `x-api-key: 9a33f333-25a1-4236-b0a4-592c44ccb417` |
| 请求体 | `{"app":{"cluster":"volcano_icl"},"user":{"uid":"redbook_pipeline"},"audio":{"voice_type":"{speaker_id}","encoding":"mp3","speed_ratio":1.0},"request":{"reqid":"{uuid}","text":"{script}","operation":"query"}}` |
| 并发 | 单张顺序请求，间隔 500ms（避免频控） |

#### Skill 6: PPTRendererSkill

| 属性 | 内容 |
|------|------|
| 职责 | 将 .pptx 每页渲染为高分辨率 PNG 帧 |
| 输入 | `06_output.pptx` |
| 输出 | `07_frames/slide_*.png` |
| 核心工具 | `LibreOffice --headless --convert-to pdf` → `pdf2image` |
| 分辨率 | 1920×1080 |

#### Skill 7: VideoComposerSkill

| 属性 | 内容 |
|------|------|
| 职责 | PNG 帧 + MP3 音频 → 按时序合并为 MP4 |
| 输入 | `07_frames/*.png` + `05_audio/*.mp3` |
| 输出 | `08_final.mp4` |
| 核心库 | `moviepy` |
| 合成规则 | 每帧显示时长 = 对应音频时长 + 0.8s 缓冲 |
| 输出参数 | H.264 + AAC, 1920×1080@30fps |

---

## 5. 数据模型 (JSON Schema)

### 5.1 01_raw_text.json — PDF 提取结果

```json
{
  "metadata": {
    "title": "论文英文标题",
    "authors": ["Author1", "Author2"],
    "page_count": 15
  },
  "sections": [
    {"name": "abstract", "content": "摘要全文..."},
    {"name": "introduction", "content": "引言..."},
    {"name": "methodology", "content": "方法..."},
    {"name": "experiments", "content": "实验..."},
    {"name": "conclusion", "content": "结论..."}
  ],
  "figures": [
    {"index": 1, "caption": "Figure 1: ...", "page": 3}
  ],
  "raw_text": "完整原文（用于 LLM 输入）"
}
```

### 5.2 02_paper_structure.json — 论文结构化摘要

```json
{
  "one_line_summary": "一句话总结论文核心贡献",
  "research_background": "该领域的研究背景",
  "core_problem": "论文主要解决什么问题",
  "key_contributions": ["贡献1", "贡献2", "贡献3"],
  "methodology_points": ["方法要点1", "方法要点2"],
  "key_results": ["结果1", "结果2"],
  "limitations": "论文局限性",
  "recommended_slide_count": 10,
  "target_audience": "目标受众描述"
}
```

### 5.3 03_slide_content.json — 幻灯片内容 + 旁白

```json
{
  "presentation_title": "小红书风格的中文标题",
  "english_title": "论文英文标题",
  "presenter_info": "汇报人：某大学 张三（博x）",
  "total_slides": 12,
  "slides": [
    {
      "slide_index": 1,
      "slide_type": "title",
      "title": "论文中文标题",
      "subtitle": "英文标题",
      "presenter": "汇报人信息",
      "bullet_points": [],
      "narration_script": "大家好！今天我们来精读一篇..."
    },
    {
      "slide_index": 2,
      "slide_type": "toc",
      "title": "目录",
      "bullet_points": ["文献介绍", "研究问题", "文章结果", "文献研究方法", "讨论"],
      "narration_script": "今天的分享会围绕这几个方面展开..."
    },
    {
      "slide_index": 3,
      "slide_type": "paper_info",
      "title": "文献介绍",
      "bullet_points": [
        "期刊：Nature Communications",
        "分区：JCR Q1 | 影响因子：16.6",
        "作者：Smith et al.",
        "单位/研究团队：MIT CSAIL"
      ],
      "narration_script": "这篇论文发表在 Nature Communications 上..."
    },
    {
      "slide_index": 4,
      "slide_type": "background",
      "title": "研究背景",
      "bullet_points": ["要点1", "要点2", "要点3"],
      "narration_script": "在介绍这篇论文之前，我们先来了解一下背景..."
    },
    {
      "slide_index": 5,
      "slide_type": "objective",
      "title": "研究目的",
      "bullet_points": ["要点1", "要点2"],
      "narration_script": "那么，这篇论文究竟想解决什么问题呢？"
    },
    {
      "slide_index": 6,
      "slide_type": "results",
      "title": "文章结果",
      "bullet_points": ["结果1", "结果2"],
      "narration_script": "实验结果非常亮眼..."
    },
    {
      "slide_index": 7,
      "slide_type": "results",
      "title": "文章结果",
      "bullet_points": ["结果3", "结果4"],
      "narration_script": "除此之外，作者还发现..."
    },
    {
      "slide_index": 10,
      "slide_type": "methods",
      "title": "文章思路-主要研究方法",
      "bullet_points": ["方法1", "方法2", "方法3"],
      "narration_script": "那么作者是怎么做到这些效果的呢？"
    },
    {
      "slide_index": 14,
      "slide_type": "discussion",
      "title": "讨论",
      "bullet_points": ["讨论要点1", "讨论要点2"],
      "narration_script": "最后我们来讨论一下这篇论文的意义..."
    },
    {
      "slide_index": 16,
      "slide_type": "ending",
      "title": "感谢聆听",
      "bullet_points": [],
      "narration_script": "以上就是今天的分享内容，感谢大家的观看！"
    }
  ],
  "estimated_total_duration_seconds": 720
}
```

### 5.4 voice_clone_result.json — 音色克隆结果

```json
{
  "speaker_id": "your_clone_voice_id",
  "status": "success",
  "created_at": "2026-06-09T10:00:00Z",
  "source_file": "source_voice/source.mp3"
}
```

---

## 6. 技术栈

| 层级 | 选型 | 理由 |
|------|------|------|
| 语言 | Python 3.11+ | 生态丰富，AI/LLM 库支持最好 |
| PDF 解析 | PyMuPDF (fitz) | 速度快，文本提取精度高，支持双栏 |
| LLM | Kimi (moonshot-v1-8k) | 中文理解优秀，API 稳定 |
| PPT 操作 | python-pptx | 直接操作 .pptx XML，与模版兼容 |
| TTS | 火山引擎 Mega-TTS | 支持音色克隆，中文语音质量优秀 |
| PPT 渲染 | LibreOffice headless + pdf2image | 保证样式 100% 还原 |
| 视频合成 | moviepy | API 友好，适合 10 分钟以内视频 |
| CLI | Typer + Rich | 类型安全，交互友好 |
| 配置 | Pydantic Settings + YAML | 类型安全，环境变量注入 |
| 日志 | loguru | 结构化日志 |
| 重试 | tenacity | LLM / TTS API 失败自动重试 |

---

## 7. 目录结构

```
redbook-pipeline/
├── README.md
├── PRD.md                          # 本文档
├── pyproject.toml                  # 依赖管理
├── .env                            # API Keys（git ignore）
├── .gitignore
│
├── config/
│   ├── settings.yaml               # 主配置
│   └── prompts/                    # LLM Prompt 模版
│       ├── paper_analysis.md
│       └── slide_generation.md
│
├── assets/
│   └── template.pptx               # PPT 模版
│
├── src/redbook_pipeline/
│   ├── __init__.py
│   ├── cli.py                      # Typer CLI
│   ├── pipeline.py                 # 全链路编排
│   ├── config.py                   # 配置加载
│   │
│   ├── skills/
│   │   ├── __init__.py
│   │   ├── base.py                 # BaseSkill 抽象基类
│   │   ├── s01_pdf_parser.py
│   │   ├── s02_paper_analyzer.py
│   │   ├── s03_slide_generator.py
│   │   ├── s04_ppt_builder.py
│   │   ├── s05_voice_clone.py      # 音色克隆（首次）
│   │   ├── s05b_tts_synthesizer.py # TTS 合成
│   │   ├── s06_ppt_renderer.py
│   │   └── s07_video_composer.py
│   │
│   ├── models/                     # Pydantic 数据模型
│   │   ├── paper.py
│   │   └── slide.py
│   │
│   └── utils/
│       ├── logger.py
│       ├── retry.py
│       ├── volcengine_tts.py       # 火山 TTS 客户端
│       └── libreoffice.py
│
├── outputs/                        # 运行时产物（git ignore）
│   └── {job_id}/
│       ├── 00_meta.json
│       ├── 01_raw_text.json
│       ├── 02_paper_structure.json
│       ├── 03_slide_content.json
│       ├── 04_voice_clone_result.json
│       ├── 05_audio/
│       │   ├── slide_01.mp3
│       │   └── ...
│       ├── 06_output.pptx
│       ├── 07_frames/
│       │   ├── slide_001.png
│       │   └── ...
│       └── 08_final.mp4
│
└── tests/
    ├── fixtures/
    └── test_*.py
```

---

## 8. CLI 接口

```bash
# 全链路执行（首次含音色克隆）
redbook run paper.pdf

# 强制重新执行（包括重新克隆音色）
redbook run paper.pdf --force

# 从指定步骤开始（断点续跑）
redbook run paper.pdf --from tts_synthesizer

# 只运行单一步骤（调试）
redbook run paper.pdf --only ppt_builder

# 查看 Job 状态
redbook status 20260609_143022_attention_is_all

# 恢复中断的 Job
redbook resume 20260609_143022_attention_is_all
```

---

## 9. 实施路线图

### Phase 1 — MVP（预估 2 周）

| 优先级 | 任务 | 工作量 |
|--------|------|--------|
| P0 | 项目骨架 + BaseSkill + CLI | 1 天 |
| P0 | PDF 解析器 | 1 天 |
| P0 | Kimi LLM 内容生成（论文分析 + 幻灯片生成） | 2 天 |
| P0 | PPT 模版填充（含动态文本框 + 删多余页） | 1.5 天 |
| P0 | 火山引擎音色克隆 + TTS 合成 | 1.5 天 |
| P0 | PPT 渲染（LibreOffice） | 0.5 天 |
| P0 | 视频合成（moviepy） | 1 天 |
| P1 | Prompt 精调 + 全链路集成测试 | 1.5 天 |

**MVP 产出**: 输入任意 PDF，10 分钟内自动产出含克隆声音旁白的 PPT 视频。

### Phase 2 — 完善（预估 1.5 周）

- LLM Prompt 精调（小红书风格、口语化旁白）
- 重试机制（tenacity）
- PDF 双栏论文处理
- 论文图表提取并插入 PPT
- TTS 并发优化
- 视频过渡效果
- 单元测试

### Phase 3 — 扩展（预估 2~3 周）

- Gradio Web UI（拖拽上传、实时进度）
- 批量处理模式
- 多 PPT 模版支持
- 视频封面生成
- 多语言支持
- Docker 化部署

---

## 10. 风险与依赖

| 风险 | 缓解方案 |
|------|---------|
| LibreOffice 未安装 | 启动时检测，提示安装命令 |
| 火山引擎音色克隆训练时间长 | speaker_id 持久化，仅首次克隆 |
| LLM 输出 JSON 格式不稳定 | Pydantic 校验 + 重试 + 明确 `response_format` |
| TTS API 频控 | 请求间隔 500ms，失败重试 |
| PDF 解析质量差（复杂排版）| 降级到原始文本模式，跳过结构化 |
| 模版文本框定位偏差 | 用 shape 名称匹配，而非固定索引 |

---

> 本文档已根据实际资源（模版结构、API 信息、声音样本位置）更新。请确认以下内容后进入开发阶段：
>
> 1. **Slide 4~15 内容区用动态添加文本框** — 是否 OK？
> 2. **多余页面自动删除** — 是否 OK？
> 3. **音色克隆用火山引擎，TTS 用 v1 API + clone voice** — 是否 OK？
> 4. **LLM 用 Kimi (moonshot-v1-8k)** — 是否 OK？
> 5. **旁白脚本风格：口语化中文，适合视频讲解** — 是否 OK？
