#!/usr/bin/env python3
"""Apply P0 font separation + P1 radius semantics."""

FILEPATH = r'd:/Code/skiil-create/tianhe-skills/dms-weekly-report/references/report_template.html'

with open(FILEPATH, 'r', encoding='utf-8') as f:
    t = f.read()

NL = '\n\n\n'

# ═══ P0: Replace font-family variable ═══
old_font = (
    '  /* ── Apple 字体栈 ── */\n'
    '\n'
    '\n'
    '  --font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display",\n'
    '\n'
    '\n'
    '                 "SF Pro Text", "Helvetica Neue", "PingFang SC",\n'
    '\n'
    '\n'
    '                 "Hiragino Sans GB", "Microsoft YaHei", sans-serif;\n'
)
new_font = (
    '  /* ── Apple 字体栈（语义层级）── */\n'
    '\n'
    '\n'
    '  --font-display: "SF Pro Display", "Helvetica Neue", "PingFang SC", sans-serif;\n'
    '\n'
    '\n'
    '  --font-body: -apple-system, BlinkMacSystemFont, "SF Pro Text", "PingFang SC",\n'
    '\n'
    '\n'
    '                "Hiragino Sans GB", "Microsoft YaHei", sans-serif;\n'
    '\n'
    '\n'
    '  --font-mono: "SF Mono", "Menlo", "Monaco", "Consolas", monospace;\n'
)
t = t.replace(old_font, new_font)
print('1a. Font vars: --font-display / --font-body / --font-mono')

# ═══ var(--font-family) → var(--font-body) ═══
count = t.count('var(--font-family)')
t = t.replace('var(--font-family)', 'var(--font-body)')
print(f'1b. var(--font-family) → var(--font-body): {count} replacements')

# ═══ P0: Add font-display to large text elements ═══
targets = [
    # .kpi-card .value
    ('.kpi-card .value {\n'
     '\n'
     '\n'
     '  font-size: 34px;\n'
     '\n'
     '\n'
     '  font-weight: 700;\n',
     '  font-size: 34px;\n'
     '\n'
     '\n'
     '  font-weight: 700;\n'
     '\n'
     '\n'
     '  font-family: var(--font-display);\n'),
    # .glass-nav-brand-text h1
    ('.glass-nav-brand-text h1 {\n'
     '\n'
     '\n'
     '  font-size: 15px;\n'
     '\n'
     '\n'
     '  font-weight: 700;\n',
     '  font-size: 15px;\n'
     '\n'
     '\n'
     '  font-weight: 700;\n'
     '\n'
     '\n'
     '  font-family: var(--font-display);\n'),
    # .section-title
    ('.section-title {\n'
     '\n'
     '\n'
     '  font-size: 20px;\n'
     '\n'
     '\n'
     '  font-weight: 700;\n',
     '  font-size: 20px;\n'
     '\n'
     '\n'
     '  font-weight: 700;\n'
     '\n'
     '\n'
     '  font-family: var(--font-display);\n'),
    # .sub-section-title
    ('.sub-section-title {\n'
     '\n'
     '\n'
     '  font-size: 18px;\n'
     '\n'
     '\n'
     '  font-weight: 700;\n',
     '  font-size: 18px;\n'
     '\n'
     '\n'
     '  font-weight: 700;\n'
     '\n'
     '\n'
     '  font-family: var(--font-display);\n'),
]
for old_start, new_start in targets:
    if old_start in t:
        t = t.replace(old_start, new_start)
print('1c. font-display applied to: .value, h1, .section-title, .sub-section-title')

# ═══ Add font-mono to number classes ═══
t = t.replace(
    '.number-format { font-variant-numeric: tabular-nums; }',
    '.number-format { font-variant-numeric: tabular-nums; font-family: var(--font-mono); }'
)
t = t.replace(
    'td.number-right, th.number-right {\n'
    '\n'
    '\n'
    '  text-align: right;\n'
    '\n'
    '\n'
    '  font-variant-numeric: tabular-nums;\n'
    '\n'
    '\n'
    '}',
    'td.number-right, th.number-right {\n'
    '\n'
    '\n'
    '  text-align: right;\n'
    '\n'
    '\n'
    '  font-variant-numeric: tabular-nums;\n'
    '\n'
    '\n'
    '  font-family: var(--font-mono);\n'
    '\n'
    '\n'
    '}'
)
print('1d. font-mono added to number-format / number-right')

# ═══ P1: Replace radius definitions ═══
old_radius = (
    '  /* ── Squircle 大圆角 ── */\n'
    '\n'
    '\n'
    '  --radius:     16px;\n'
    '\n'
    '\n'
    '  --radius-sm:  10px;\n'
    '\n'
    '\n'
    '  --radius-lg:  12px;\n'
    '\n'
    '\n'
    '  --radius-xs:  6px;\n'
    '\n'
    '\n'
    '  --radius-pill: 9999px;\n'
)
new_radius = (
    '  /* ── Squircle 大圆角（语义层级）── */\n'
    '\n'
    '\n'
    '  --radius-card: 16px;    /* KPI / 图表 / 表格容器 */\n'
    '\n'
    '\n'
    '  --radius-sm:  10px;     /* 表单控件 / 内嵌卡片 */\n'
    '\n'
    '\n'
    '  --radius-lg:  20px;     /* 大卡片 / Hero 区域 */\n'
    '\n'
    '\n'
    '  --radius-xs:   6px;     /* 极小元素 */\n'
    '\n'
    '\n'
    '  --radius-pill: 9999px;  /* 胶囊按钮 */\n'
    '\n'
    '\n'
    '  --radius-squircle: 18%; /* Apple 风格超级椭圆，用于品牌图标 */\n'
)
t = t.replace(old_radius, new_radius)

# var(--radius) → var(--radius-card)
count_rad = t.count('var(--radius)')
t = t.replace('var(--radius)', 'var(--radius-card)')
print(f'2a. var(--radius) → var(--radius-card): {count_rad} replacements')

# Brand icon → squircle
t = t.replace(
    '.glass-nav-brand-icon {\n'
    '\n'
    '\n'
    '  width: 32px;\n'
    '\n'
    '\n'
    '  height: 32px;\n'
    '\n'
    '\n'
    '  background: var(--primary);\n'
    '\n'
    '\n'
    '  border-radius: 8px;\n',
    '.glass-nav-brand-icon {\n'
    '\n'
    '\n'
    '  width: 32px;\n'
    '\n'
    '\n'
    '  height: 32px;\n'
    '\n'
    '\n'
    '  background: var(--primary);\n'
    '\n'
    '\n'
    '  border-radius: var(--radius-squircle);\n'
)
print('2b. Brand icon → --radius-squircle (18%)')

# ═══ Write & verify ═══
with open(FILEPATH, 'w', encoding='utf-8') as f:
    f.write(t)

assert 'getFilteredRows' in t

checks = [
    ('--font-display defined', '--font-display:' in t),
    ('--font-body defined', '--font-body:' in t),
    ('--font-mono defined', '--font-mono:' in t),
    ('--radius-card defined', '--radius-card:' in t),
    ('--radius-squircle defined', '--radius-squircle:' in t),
    ('no --font-family', '--font-family' not in t),
    ('no var(--font-family)', 'var(--font-family)' not in t),
    ('font-display applied >=5', t.count('var(--font-display)') >= 5),
    ('font-body applied >=9', t.count('var(--font-body)') >= 9),
    ('font-mono applied >=2', t.count('var(--font-mono)') >= 2),
    ('radius-card applied >=5', t.count('var(--radius-card)') >= 5),
    ('radius-squircle used', 'var(--radius-squircle)' in t),
    ('JS intact', 'getFilteredRows' in t and 'computeAggregates' in t),
]
for name, ok in checks:
    print(f'  [{"PASS" if ok else "FAIL"}] {name}')
print(f'\n  {sum(1 for _,o in checks if o)}/{len(checks)} passed')
