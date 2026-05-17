# 医学论文每日摘要服务 / Medical Research Daily Digest

每天自动抓取 arXiv 和 PubMed 上最新的医疗健康论文，用 LLM 按主题分类并生成摘要，通过邮件发送给你。

---

## 项目结构

```
automate paper/
├── main.py                  # 主程序 & 定时调度器
├── config.py                # 配置（读取 .env）
├── models.py                # Paper 数据类
├── fetchers/
│   ├── arxiv_fetcher.py     # 从 arXiv 抓取论文
│   └── pubmed_fetcher.py    # 从 PubMed 抓取论文
├── processors/
│   ├── llm_processor.py     # LLM 分类 + 摘要生成
│   └── pdf_parser.py        # PDF 文本提取（可选）
├── notifier/
│   └── email_sender.py      # HTML 邮件构建 & 发送
├── logs/                    # 自动创建，存放运行日志和 HTML 备份
├── requirements.txt
└── .env                     # 你的私钥（不要提交到 Git）
```

---

## 快速开始

### 1. 安装依赖

```powershell
cd "d:\Xuwei\CIRES works\automate paper"
pip install -r requirements.txt
```

### 2. 配置环境变量

复制示例文件并填写你的信息：

```powershell
copy .env.example .env
```

打开 `.env`，至少填写以下字段：

| 字段 | 说明 |
|------|------|
| `OPENAI_API_KEY` | OpenAI API Key（[获取地址](https://platform.openai.com/api-keys)）|
| `EMAIL_SENDER` | 发件邮箱（推荐 Gmail） |
| `EMAIL_PASSWORD` | Gmail **App Password**（见下方说明） |
| `EMAIL_RECIPIENT` | 收件邮箱 |
| `PUBMED_EMAIL` | 你的邮箱（NCBI 要求，用于标识应用） |

#### Gmail App Password 设置方法
1. 登录 Google 账户 → **安全性**
2. 开启两步验证
3. 搜索 **应用专用密码** → 新建 → 填入 `EMAIL_PASSWORD`

> 注意：不要使用你的 Gmail 登录密码，必须用 App Password。

### 3. 立即测试运行

```powershell
python main.py --run-now
```

- 如果邮件发送失败，HTML 报告会自动保存到 `logs/digest_YYYYMMDD.html`，用浏览器打开即可查看。

### 4. 启动定时服务（每天自动运行）

```powershell
python main.py --schedule-only
```

程序会在 `.env` 中 `SCHEDULE_TIME`（默认 `08:00`）每天自动运行，保持窗口开着即可。

---

## Windows 后台服务（推荐）

用 Windows 任务计划程序让程序开机自启、无需保持窗口打开：

```powershell
# 在 PowerShell（管理员）中运行
$action  = New-ScheduledTaskAction -Execute "python" -Argument '"d:\Xuwei\CIRES works\automate paper\main.py" --run-now' -WorkingDirectory "d:\Xuwei\CIRES works\automate paper"
$trigger = New-ScheduledTaskTrigger -Daily -At "08:00"
Register-ScheduledTask -TaskName "MedicalDigest" -Action $action -Trigger $trigger -RunLevel Highest
```

之后可在「任务计划程序」窗口中管理。

---

## 配置说明（.env）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `LLM_MODEL` | `gpt-4o-mini` | 可换成 `gpt-4o`（更准，更贵）|
| `MAX_PAPERS_ARXIV` | `30` | 每天从 arXiv 最多抓取篇数 |
| `MAX_PAPERS_PUBMED` | `20` | 每天从 PubMed 最多抓取篇数 |
| `DAYS_BACK` | `1` | 往前看几天（周一建议设为 `3` 覆盖周末）|
| `SCHEDULE_TIME` | `08:00` | 每日运行时间（24 小时制）|
| `DOWNLOAD_PDFS` | `false` | 是否下载全文 PDF（会增加处理时间）|
| `MAX_PDF_PAPERS` | `5` | 最多下载几篇 PDF |
| `ARXIV_SEARCH_QUERY` | *(内置医学关键词)* | 自定义 arXiv 搜索词 |
| `PUBMED_SEARCH_QUERY` | *(内置 AI+医学)* | 自定义 PubMed 搜索词 |

---

## 邮件示例

每封邮件包含：
- 当天论文数量、主题数、高影响力论文数
- AI 生成的今日综述导言
- 按主题分组的论文卡片，每张卡片显示：
  - 标题（链接到原文）、作者、来源、发布日期
  - ★★★★☆ 相关性评分
  - 2-3 句白话摘要
  - 关键发现列表
  - PDF 直链

---

## 论文主题分类

LLM 会将论文自动分入以下类别：

- Clinical Research & Trials
- Medical AI & Machine Learning
- Drug Discovery & Pharmacology
- Genomics & Precision Medicine
- Medical Imaging & Diagnostics
- Public Health & Epidemiology
- Cardiology & Cardiovascular Disease
- Oncology & Cancer Research
- Infectious Diseases
- Neurology & Brain Disorders
- Surgery & Procedures
- Mental Health & Psychiatry
- Other Healthcare Topics

---

## 常见问题

**Q: arXiv 没有抓到当天的论文？**
A: arXiv 通常在美国东部时间下午更新，可以把 `SCHEDULE_TIME` 设为 `20:00` 或第二天早上，或将 `DAYS_BACK=2`。

**Q: PubMed 没有结果？**
A: PubMed 主要收录已发表论文，有时当天没有新文章属于正常现象，可以将 `DAYS_BACK=3`。

**Q: 邮件发送失败？**
A: 程序会自动将 HTML 报告保存到 `logs/` 目录，直接用浏览器打开即可阅读。

**Q: 如何减少 API 费用？**
A: 将 `LLM_MODEL=gpt-4o-mini` 并适当降低 `MAX_PAPERS_ARXIV` 和 `MAX_PAPERS_PUBMED`。
