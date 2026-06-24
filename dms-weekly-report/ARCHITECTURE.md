# DMS 询价周报 — HTML 报表渲染架构

## 目录结构

```
dms-weekly-report/
├── scripts/
│   ├── generate_html_report.py    # 薄入口函数，委托给 renderers/
│   ├── run_weekly_report.py       # 主编排脚本（登录→筛选→提取→生成报表）
│   ├── renderers/                 # 报表渲染核心模块包
│   │   ├── __init__.py            # 包导出
│   │   ├── data_reader.py         # XlsxDataReader — xlsx 数据源
│   │   ├── data_transform.py      # 数据映射 + 聚合统计
│   │   ├── context_builder.py     # ReportContextBuilder — Jinja2 上下文构建
│   │   ├── renderer.py            # HtmlReportRenderer — 核心渲染器
│   │   ├── template_engine.py     # Jinja2 引擎封装
│   │   └── cli_entry.py           # 命令行入口
│   └── tests/
│       ├── test_generate_html_report.py  # 向后兼容测试
│       └── test_renderers.py             # 新模块测试
├── references/
│   ├── templates/                 # Jinja2 组件模板
│   │   ├── index.html             # 入口（include base + body + scripts）
│   │   ├── base.html              # HTML shell + CSS Design Tokens
│   │   ├── body.html              # HTML 结构（header, tabs, cards, charts, table, footer）
│   │   └── scripts.html           # 前端 JS 数据管道
│   └── report_template.html       # (保留) 旧单文件模板，不再使用
└── ARCHITECTURE.md                # 本文档
```

## 数据流

```
数据源 (xlsx / 未来 API)
    │
    ▼
XlsxDataReader.read()
    │
    ▼  list[list[Any]]  (原始行，每行 21 列)
    │
compute_rows_detail()
    │
    ▼  list[RowDetail]  (有名字典列表，camelCase)
    │
    ├── compute_aggregations()  ───→  AGGREGATIONS_JSON
    │
    ▼
ReportContextBuilder.build(rows_detail, query_range)
    │
    ▼  dict  (Jinja2 上下文字典)
    │     ├── REPORT_DATE_RANGE, FOOTER_TEXT, …   (文本占位符)
    │     ├── ROWS_DETAIL_JSON                    (行数据，预序列化)
    │     └── AGGREGATIONS_JSON                   (聚合统计，预计算)
    │
render_template("index.html", context)
    │  (Jinja2 处理 extends/include + {{PLACEHOLDER}})
    ▼
完整 HTML 字符串  →  写入文件
```

## 模块职责

| 模块 | 职责 | 关键 API |
|------|------|----------|
| `data_reader.py` | 从数据源读取原始行 | `XlsxDataReader(file_path).read()` |
| `data_transform.py` | 行→字典映射 + 聚合 | `compute_rows_detail()`, `compute_aggregations()` |
| `context_builder.py` | 构建 Jinja2 渲染上下文 | `ReportContextBuilder().build(rows_detail, query_range)` |
| `renderer.py` | 渲染管线编排 | `HtmlReportRenderer().render(rows_data, query_range, output_path)` |
| `template_engine.py` | Jinja2 封装 | `render_template(template_name, context)` |
| `cli_entry.py` | 命令行解析 + 执行 | `main()` |

## 设计决策

### 为什么用 Jinja2 而非 str.replace？
- `_KeepPlaceholder` 机制：未定义的 `{{PLACEHOLDER}}` 保留原文，不会静默消失
- 模板组件化：`{% include %}` 将 10787 行单文件拆为 3 个可维护的组件
- 上下文集中管理：所有占位符在 `context_builder.py` 一处定义，无需分散替换

### 为什么 Renderer 模式而非纯函数？
- 可注入性：可注入 mock context_builder 或 template_engine 进行单元测试
- 可扩展性：后续可派生 `PdfReportRenderer`，复用现有上下文构建逻辑
- 职责清晰：渲染管线（数据→上下文→渲染→输出）在一个类的 `render()` 方法中一目了然

### 预计算聚合的意义？
- `compute_aggregations()` 在 Python 侧计算 KPI 统计，注入为 `AGGREGATIONS_JSON`
- 前端 JS 仍通过 `ROWS_DETAIL` 实时派生聚合（备份/动态筛选用）
- 预计算值可供模板直接渲染，减轻前端计算负担，也可作为快速加载的 fallback

## 向后兼容

- `from generate_html_report import generate_html_report` 仍可调用
- `_simple_replace` / `_replace_json_field` 保留导出（供外部脚本使用）
- `run_weekly_report.py` 调用 `generate_html_report(rows_data, query_range, path)` 不变
- 测试全部通过（465 tests, 0 failures）
