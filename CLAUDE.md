# 项目说明

## Skill 同步规则

修改工作区 `d:\Code\Skills开发\` 下任何 skill 的脚本后，必须**先删除目标目录再全量复制**同步到 `$HOME/.claude/skills/`，避免 `cp -r` 在目标已存在时产生嵌套目录：

```bash
# dms-weekly-report（全目录覆盖：SKILL.md + scripts/ + assets/ 等）
rm -rf "$HOME/.claude/skills/dms-weekly-report/"
cp -r "d:/Code/Skills开发/tianhe-skills/dms-weekly-report/" "$HOME/.claude/skills/dms-weekly-report/"

# dms-inquiry-bom（全目录覆盖：SKILL.md + scripts/ + assets/ 等）
rm -rf "$HOME/.claude/skills/dms-inquiry-bom/"
cp -r "d:/Code/Skills开发/tianhe-skills/dms-inquiry-bom/" "$HOME/.claude/skills/dms-inquiry-bom/"

# dms-inventory
rm -rf "$HOME/.claude/skills/dms-inventory/"
cp -r "d:/Code/Skills开发/tianhe-skills/dms-inventory/" "$HOME/.claude/skills/dms-inventory/"
```

> ⚠️ 注意：`cp -r src/ dest/` 当 `dest/` 已存在时，会在 dest 内创建 `src/` 子目录（即 `dest/src/`），导致 `scripts/scripts/` 嵌套问题。必须先 `rm -rf` 再 `cp -r`。

## 测试验证规则（修改代码后必须执行）

修改工作区 `d:\Code\Skills开发\tianhe-skills\` 下**任意脚本**后，必须执行以下步骤，**不得跳过**：

1. **查看对应 skill 下是否存在测试用例**（`tests/` 或 `scripts/tests/` 目录下的 `test_*.py`）
2. **如果没有对应的测试用例，必须先补充测试用例**，覆盖修改的代码逻辑
3. **运行所有相关测试用例**，确认全部通过
4. **如果测试用例不完整**（覆盖不到修改的代码），必须补充测试用例
5. **所有测试全部通过后，才向用户返回结果**
6. 任何测试失败时，先修复问题再重新运行，不得跳过失败测试

### 测试套件速查

| Skill | 脚本文件 | 测试文件 | 运行命令 |
|-------|---------|---------|---------|
| dms-inquiry-bom | `scripts/dms_credentials.py` | `tests/test_dms_credentials.py` | `python dms-inquiry-bom/tests/test_dms_credentials.py` |
| dms-inquiry-bom | `scripts/inventory_query.py` | `tests/test_inventory_query.py` | `python dms-inquiry-bom/tests/test_inventory_query.py` |
| dms-inquiry-bom | `scripts/inverter_config.py` | `tests/test_inverter_config.py` | `python dms-inquiry-bom/tests/test_inverter_config.py` |
| dms-inquiry-bom | `scripts/run_inquiry_bom.py` | `tests/test_run_inquiry_bom.py` | `python dms-inquiry-bom/tests/test_run_inquiry_bom.py` |
| dms-inquiry-bom | `scripts/browser_manager.py` | ❌ 无测试 | — |
| dms-inquiry-bom | `scripts/fill_product_info.py` | ❌ 无测试 | — |
| dms-inquiry-bom | `scripts/run_inquiry_extract.py` | ❌ 无测试 | — |
| dms-weekly-report | `scripts/resolve_date_range.py` | `scripts/tests/test_resolve_date_range.py` | `python dms-weekly-report/scripts/tests/test_resolve_date_range.py` |
| dms-weekly-report | `scripts/column_definitions.py` | `scripts/tests/test_column_definitions.py` | `python dms-weekly-report/scripts/tests/test_column_definitions.py` |
| dms-weekly-report | `scripts/excel_styles.py` | `scripts/tests/test_excel_styles.py` | `python dms-weekly-report/scripts/tests/test_excel_styles.py` |
| dms-weekly-report | `scripts/run_weekly_report.py` | `scripts/tests/test_run_weekly_report.py` | `python dms-weekly-report/scripts/tests/test_run_weekly_report.py` |
| dms-weekly-report | `scripts/dms_credentials.py` | ❌ 无测试 | — |
| dms-weekly-report | `scripts/generate_html_report.py` | ❌ 无测试 | — |
| dms-weekly-report | `scripts/bom_parser.py` | `scripts/tests/test_bom_parser.py` | `python dms-weekly-report/scripts/tests/test_bom_parser.py` |
| dms-weekly-report | `scripts/approval_parser.py` | `scripts/tests/test_approval_parser.py` | `python dms-weekly-report/scripts/tests/test_approval_parser.py` |
| dms-weekly-report | `scripts/orders_checker.py` | `scripts/tests/test_orders_checker.py` | `python dms-weekly-report/scripts/tests/test_orders_checker.py` |
| dms-inventory | `scripts/*.py` | ❌ 全部无测试 | — |

> 对无测试的脚本文件，修改后至少补充覆盖修改点的基础测试用例。



## Skill 编写规范

涉及编写或修改 SKILL.md 时，必须参考 [SKILL-WRITING-GUIDE.md](./SKILL-WRITING-GUIDE.md) 中的规范，包括：

### 核心原则

1. **精准触发描述** — `description` 字段必须包含中英文触发关键词，并明确排除不适用场景
2. **傻瓜化工作流** — 使用编号步骤（步骤 1、步骤 2……），关键决策点写明条件分支
3. **模块化设计** — 主文件控制在 300 行以内，复杂内容拆分到 `references/`、`scripts/` 子目录
4. **表格承载结构化信息** — 参数说明、错误码等用 Markdown 表格，不用段落描述
5. **持续迭代优化** — 每次执行后回顾反思，更新 SKILL.md

### 自查清单（编写后必须逐项检查）

- [ ] 有 YAML Frontmatter，description 包含触发关键词和否定排除
- [ ] Workflow 使用编号步骤，附带可执行的命令
- [ ] 参数说明使用表格
- [ ] 有异常处理 / FAQ 章节
- [ ] 有安全约束，明确允许和禁止的操作
- [ ] 主文件不超过 300 行
- [ ] 脚本路径使用绝对路径

## Git 提交规范

如果需要提交代码，采用约定式提交（Conventional Commits）格式：

```text
<type>(<scope>): <简短描述>

<可选详细说明，每行不超过 72 字符>
```

### 类型（type）

| 类型       | 用途                    |
| ---------- | ----------------------- |
| `feat`     | 新功能                  |
| `fix`      | Bug 修复                |
| `refactor` | 重构（不改变外部行为）  |
| `docs`     | 文档变更（SKILL.md 等） |
| `test`     | 添加或修改测试          |
| `perf`     | 性能优化                |
| `chore`    | 构建、依赖、工具配置等  |
| `ci`       | CI/CD 配置变更          |

### 范围（scope，可选）

- `credentials` — 凭据检测相关
- `inventory` — 库存查询相关
- `product-info` — 产品信息填写相关
- `browser` — 浏览器管理相关
- `weekly-report` — 周报生成相关
- `skill` — SKILL.md 文档

### 示例

```
feat(inventory): 支持按物料编码聚合所有仓库的库存总量
refactor(credentials): 提取 DMS 凭据检测为独立共享模块
docs(skill): 更新周报反思流程和 headless 模式说明
```
