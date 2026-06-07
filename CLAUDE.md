# 项目说明

## Git 提交规范

采用约定式提交（Conventional Commits）格式：

```text
<type>(<scope>): <简短描述>

<可选详细说明，每行不超过 72 字符>
```

### 类型（type）

| 类型 | 用途 |
|------|------|
| `feat` | 新功能 |
| `fix` | Bug 修复 |
| `refactor` | 重构（不改变外部行为） |
| `docs` | 文档变更（SKILL.md 等） |
| `test` | 添加或修改测试 |
| `perf` | 性能优化 |
| `chore` | 构建、依赖、工具配置等 |
| `ci` | CI/CD 配置变更 |

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

## Skill 同步规则

修改工作区 `d:\Code\Skills开发\` 下任何 skill 的脚本后，必须**先删除目标目录再全量复制**同步到 `C:\Users\Administrator\.claude\skills\`，避免 `cp -r` 在目标已存在时产生嵌套目录：

```bash
# dms-weekly-report（全目录覆盖：SKILL.md + scripts/ + assets/ 等）
rm -rf "C:/Users/Administrator/.claude/skills/dms-weekly-report/"
cp -r "d:/Code/Skills开发/tianhe-skills/dms-weekly-report/" "C:/Users/Administrator/.claude/skills/dms-weekly-report/"

# dms-inquiry-bom（全目录覆盖：SKILL.md + scripts/ + assets/ 等）
rm -rf "C:/Users/Administrator/.claude/skills/dms-inquiry-bom/"
cp -r "d:/Code/Skills开发/tianhe-skills/dms-inquiry-bom/" "C:/Users/Administrator/.claude/skills/dms-inquiry-bom/"
```

> ⚠️ 注意：`cp -r src/ dest/` 当 `dest/` 已存在时，会在 dest 内创建 `src/` 子目录（即 `dest/src/`），导致 `scripts/scripts/` 嵌套问题。必须先 `rm -rf` 再 `cp -r`。
