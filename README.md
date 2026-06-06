# 🌞 天合光能 — DMS Skills

天合光能 DMS 系统的 Claude Code 自动化工具集。

## Skills

| Skill | 用途 | 安装 |
|-------|------|------|
| `dms-inquiry-bom` | 非标询价：提取待办 → 确认需求 → 库存匹配 → 生成 BOM → 填写产品信息 | `npx skills add Meiuxs/tianhe-skills --skill dms-inquiry-bom -g` |
| `dms-weekly-report` | 询价周报：自动提取已办询价，生成 Excel 汇总报告 | `npx skills add Meiuxs/tianhe-skills --skill dms-weekly-report -g` |

## 安装

```bash
# 安装单个 skill
npx skills add Meiuxs/tianhe-skills --skill dms-inquiry-bom -g
npx skills add Meiuxs/tianhe-skills --skill dms-weekly-report -g

# 前置依赖
pip install playwright openpyxl pandas calamine
playwright install chromium
```

## 目录结构

```
tianhe-skills/
├── dms-inquiry-bom/        # 非标询价自动化
│   ├── SKILL.md
│   ├── scripts/
│   ├── assets/
│   └── references/
├── dms-weekly-report/      # 询价周报自动化
│   ├── SKILL.md
│   ├── scripts/
├── README.md
└── .gitignore
```
