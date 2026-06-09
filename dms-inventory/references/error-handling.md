# 异常处理

| 场景 | 处理方式 |
|:-----|:---------|
| 库存文件未找到 | 编排器会报错，根据错误信息确认 assets/ 目录是否有 Excel 文件（异常时再检查，不要提前确认） |
| 查询结果全部为空 | 确认输入 JSON 中功率/类型参数是否正确 |
| 编排器报错 | 查看错误输出，检查 JSON 格式是否符合参考文档 |
| 用户指定规格库存为 0 | 查看 `alternatives` 推荐相近功率，走用户确认。如果用户选了"接受替代" → 更新 power 重跑编排器 |
| 组件无库存且用户选了"精确匹配" | 终止，告知用户需自筹组件 |
| 替代后逆变器组合为空 | 提示用户调整容配比或品牌偏好，或走用户自筹 |
| 已有逆变器功率被忽略（`existing_inverter_kw: 0`） | 编排器现在会发出 `[警告]`；同时确认使用 `--params $(cat)` 而非 `--params-file`。见下条 |
| Windows MSYS2 路径翻译导致 `--params-file` 读到错误文件 | Git Bash 中 `/tmp/` 被 MSYS2 翻译到 `C:\Users\...\Temp\`，与 Write 工具写入的路径可能不一致。**解决：** 始终使用 `--params "$(cat $TMP_DIR/input.json)"` 而非 `--params-file`，避免文件路径依赖 |
| 输出路径含中文导致乱码 | `--output-file` 必须用 `$TMP_DIR/` 纯 ASCII 路径 |
| 终端打印中文变 `����` 乱码 | 调用 Python 时加 `PYTHONIOENCODING=utf-8`；cmd 环境先执行 `chcp 65001` |
| `python -c` 读取结果时报 `unicodeescape` SyntaxError | Windows 路径中的 `\U` 被 Python 解释为 Unicode 转义。**解决：** 使用固定路径（如 `/tmp/dms_inventory`）代替 `python -c` 动态获取 tempdir；或在 Python 脚本中用 `os.environ.get('TMP')` 而非 `tempfile.gettempdir()` |
| Python 写入文件时报 `No such file or directory` | 不同进程（bash vs Python）中 $TMP_DIR 路径不一致。**解决：** Python 脚本中统一用 `os.environ.get('TMP', '/tmp')` 或 `os.path.join(tempfile.gettempdir(), 'dms_inventory')` 并 `os.makedirs(exist_ok=True)`，不依赖 bash 变量 |
