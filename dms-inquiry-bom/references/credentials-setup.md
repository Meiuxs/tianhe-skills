# DMS 凭据配置指南

## 配置方式

DMS 登录凭据通过环境变量读取，**不硬编码密码**。检测逻辑集中在 `scripts/dms_credentials.py`。

### Bash / Git Bash（临时）

```bash
export DMS_USER="your_email@trinapower.com"
export DMS_PASSWORD="your_password"
```

### PowerShell（临时）

```powershell
$env:DMS_USER="your_email@trinapower.com"
$env:DMS_PASSWORD="your_password"
```

### 永久配置

将上述命令添加到 `~/.bashrc`（Bash）或 `$PROFILE`（PowerShell）。

## 检测逻辑

1. 当前 shell 环境变量
2. shell profile（先直读 `export`，再 bash 兜底）
3. PowerShell 用户变量

## 验证

```bash
python ~/.claude/skills/dms-inquiry-bom/scripts/dms_credentials.py --check-browser
```

输出示例（凭据就绪）：

```
DMS_USER=xxx@trinapower.com
DMS_PASSWORD=xxx
SOURCE=当前环境变量
```

输出 `NOT_FOUND` 时，向用户展示上述配置步骤。
