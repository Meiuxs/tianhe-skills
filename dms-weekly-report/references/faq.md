# 常见问题排查

> 被 `SKILL.md` 的 FAQ 章节引用。遇到具体问题时查阅，不需要在每次执行时阅读。

### Q: 环境检查失败怎么办？

```
运行 check_environment.py 查看具体问题：
  python "$SKILL_DIR/scripts/check_environment.py"

常见失败原因及修复：
  1. Python 版本过低 → 升级到 3.9+
  2. 依赖包缺失 → pip install playwright openpyxl
  3. Chromium 未安装 → playwright install chromium
  4. 凭据未配置 → 见下方「未配置环境变量」
```

### Q: 环境检查通过但仍报错？

```
可能原因：
  - check_environment.py 使用 --quick 模式跳过了部分检查
  - 运行完整检查：python check_environment.py（不带 --quick）
  - 检查 Python 解释器是否在虚拟环境中
```

### Q: 脚本报"未配置环境变量"但实际已配置

```
原因：当前 shell 未加载 profile 文件
解决：
  source ~/.bashrc                        # Bash
  或重启终端后重试
  或用完整命令：bash -c 'source ~/.bashrc && python ...'
```

### Q: 提取到 0 条记录

```
可能原因：
  - 本周确实没有已办结的询价
  - 日期范围不对（用 --start-date 放大范围排查）
  - DMS 页面"已办流程"菜单选择器失效
```

### Q: DMS 页面结构变化导致选择器失效

```
现象：脚本能登录但提取不到数据
解决：需要更新 run_weekly_report.py 中的选择器常量
      主要关注：表格行选择器、表单字段选择器
      开启 --verbose 查看详细调试输出
```

### Q: Excel 文件保存失败

```
原因：目标文件被 Excel 或其他程序占用
解决：脚本自动使用 "{文件名}_v2.xlsx" 作为备用文件名
      关闭原文件后删除旧文件再运行
```

### Q: 登录提示验证码

```
DMS 偶尔触发验证码验证，此时需要手动操作：
  1. 去掉 --headless 参数（显示浏览器）
  2. 在浏览器窗口中手动完成验证码
  3. 脚本会自动继续
```

### Q: 流程编号显示为不正确的数字

```
现象：报表中的流程编号最后几位与 DMS 系统中不一致。
原因：Excel 中该列以数字格式存储，而非文本。Excel 的 IEEE 754 双精度
     浮点数约 15-16 位有效数字，超过此范围的长编号精度丢失。
解决：在 Excel 中将该列格式设为「文本」后重新导出 xlsx。
     本 skill 运行时会检测此情况并输出 stderr 提醒。
```
