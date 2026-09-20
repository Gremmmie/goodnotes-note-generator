# goodnotes-note-generator

把资料（论文、PDF、课件、截图、长文本）转换成 Goodnotes 风格的手写笔记图，并支持把本地资料打包给**读不到本地文件**的网页端 AI 出图。

An agent skill (agent skill format, per the open agent skills standard) for Codex / ChatGPT: turn source material into realistic handwritten note images, and build web-chat handoff bundles when the image generation happens in a browser.

## 内容结构

| 路径 | 作用 |
| --- | --- |
| `SKILL.md` | 主指令：默认出图模式、页面规划、视觉规范、质检清单，以及「网页端模式」 |
| `references/visual-style.md` | 视觉系统与真实感线索（白底、中英混排手写、手绘元素） |
| `references/output-patterns.md` | 6 种页面原型（concept / comparison / process / structure / problem-solution / cheat sheet）与套图设计 |
| `references/web-handoff.md` | 网页端交接包结构、粘贴用 prompt 的七段式结构、上传预算降级顺序、故障对照表 |
| `scripts/render_upload_pages.py` | 把 PDF／图片／文本渲染成可上传的页面图，并产出上传清单与上下文包 |
| `agents/openai.yaml` | UI 元数据：展示名、简介、品牌色、默认调用语 |

## 安装

技能目录放到 Codex 的 skills 路径下即可（支持软链接，Codex 会跟随链接目标扫描）：

```bash
mkdir -p ~/.codex/skills
ln -s "$PWD" ~/.codex/skills/goodnotes-note-generator   # 或者 cp -R "$PWD" ~/.codex/skills/
```

改完 skill 后 Codex 会自动检测；若未生效，重启 Codex。

## 用法

显式调用：

```text
$goodnotes-note-generator 把这篇 PDF 做成 4 页手写风笔记图：/path/to/xxx.pdf
```

隐式调用（靠 `description` 命中）：直接说「把这份资料做成 Goodnotes 风格笔记图」「做成小红书能发的 4 页手写笔记」。

网页端出图（browser chat 读不到本地文件时）：

```text
$goodnotes-note-generator 打包给网页端出图，网页端读不了我的本地文件
```

## 网页端交接包

```bash
python3 scripts/render_upload_pages.py <资料文件...> [--out DIR] [--max-files 5] [--max-mb 5] [--long-edge 2000]
```

输出目录（默认在首个来源文件旁的 `web_handoff/`，已存在且非空时自动加序号，不覆盖）：

```
web_handoff/
├── pages/                 # 可直接上传的页面图（PNG，超体积时降级 JPEG）
├── context_pack.md        # 文本摘录（不含本地绝对路径，可直接上传）
├── upload_manifest.md     # 上传清单：优先级 / 文件名 / 本地路径 / 大小 / 用途 / 准备
├── handoff.json           # 机器可读摘要
└── web_prompt.md          # 由 agent 撰写的粘贴用 prompt（脚本不生成）
```

设计原则：**本地负责拆页、压缩内容、锁定每页精确文案，网页端只负责渲染成手写风笔记图。**

## 依赖

- `pdftoppm`、`pdftotext`、`pdfinfo`（Poppler，macOS：`brew install poppler`）
- Python 3 + Pillow（`python3 -m pip install pillow`）
- 可选 `sips`（macOS 自带，HEIC 与 JPEG 兜底）

## 配色

`#005087`（deep blue）、`#86B8CE`（light blue）、`#B23939`（muted red）、`#D88080`（dusty pink），以纯白页 + 黑色／深灰正文为主。

## 许可

未声明 License。如需开源分发，请在此补充（例如 MIT）。
