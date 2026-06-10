#!/usr/bin/env python3
"""产品信息填写脚本（Element UI 版本）。

在DMS流程详情页的产品信息区域填写相关数据。

页面使用 Element UI 框架，表单结构：
  - .el-form-item > label + .el-form-item__content
  - 下拉框: .el-select > .el-input > input
  - 输入框: .el-input > input
  - 选项: .el-select-dropdown__item

用法：
  python fill_product_info.py --flow-id 2026060310435399 --component-power 715 --component-count 800
  python fill_product_info.py --flow-id 2026060310435399 --component-power 715 --component-count 800 --headless
"""

import argparse
import asyncio
import os
import sys
import traceback
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

# 导入共享浏览器管理器
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _compat  # noqa: F401, E402
from browser_manager import BrowserManager, is_on_login_page, do_login

# ==================== 配置 ====================

from dms_credentials import DMS_URL

# 字段选项常量 —— DMS 后台变更这些文本时只需修改此处
PRODUCT_TYPE = "非原装系统"
DIGITAL_PLATFORM_TYPE = "标准"
SPEC_DEFAULT = "无"
ROOF_TYPE = "无"
INSTALL_METHOD = "无"
ROW_COUNT = "无"
REMARK_TEXT = "非标准BOM，安装产生风险渠道伙伴自行承担"


# ==================== Element UI 表单操作工具 ====================

async def _locate_form_item(page, label_text: str):
    """在"产品信息"区域内定位包含指定 label 的 el-form-item。

    先定位产品信息区域（.form-row-box），再在其中搜索 form-item，
    避免全页搜索匹配到其他区域的同名 label。
    找到后自动滚动到视口内。

    Returns:
        locator | None: Playwright locator，或 None（未找到）
    """
    # 限定到产品信息区域
    product_section = page.locator('.form-row-box:has(.row-title:has-text("产品信息"))').first

    try:
        await product_section.wait_for(state="attached", timeout=5000)
    except PlaywrightTimeout:
        print(f"  [警告] {label_text}: 未找到产品信息区域", file=sys.stderr)
        return None

    form_item = product_section.locator(f'.el-form-item:has(label:has-text("{label_text}"))').first

    try:
        await form_item.wait_for(state="attached", timeout=3000)
    except PlaywrightTimeout:
        print(f"  [警告] {label_text}: 未找到表单项", file=sys.stderr)
        return None

    # 滚动到视口内 —— 解决"上下滑动找不到位置"问题
    await form_item.evaluate("el => el.scrollIntoView({block: 'center', behavior: 'instant'})")
    await page.evaluate("() => new Promise(r => setTimeout(r, 200))")

    return form_item


async def el_select_by_label(page, label_text: str, option_text: str):
    """通过 label 文本定位 el-select 并选择指定选项。

    Args:
        page: Playwright page
        label_text: 表单标签文本，如 "产品类型"
        option_text: 要选择的选项文本，如 "非原装系统"

    Returns:
        bool: 是否成功选择

    Note:
        Element UI 的 el-select input 有 readonly 属性，不能直接用 fill()。
        选项点击改用 JS evaluate 触发，绕过 Playwright 可见性/稳定性检查。
    """
    form_item = await _locate_form_item(page, label_text)
    if form_item is None:
        return False

    # 检查是否禁用（el-select readonly 属性不影响禁用判定）
    disabled = await form_item.evaluate("""el => {
        const select = el.querySelector('.el-select');
        if (!select) return false;
        if (select.classList.contains('is-disabled')) return true;
        const input = select.querySelector('.el-input');
        if (input && input.classList.contains('is-disabled')) return true;
        const inputEl = select.querySelector('input');
        if (inputEl && inputEl.disabled) return true;
        return false;
    }""")

    if disabled:
        print(f"  [跳过] {label_text}: 已禁用", file=sys.stderr)
        return False

    select_input = form_item.locator('.el-select .el-input__inner').first
    if not await select_input.is_visible(timeout=3000):
        print(f"  [警告] {label_text}: 未找到输入框", file=sys.stderr)
        return False

    # 点击输入框打开下拉（readonly 元素 click 正常）
    await select_input.click()

    # 等待下拉框出现，超时后尝试重新点击一次
    try:
        await page.locator('.el-select-dropdown:visible').first.wait_for(state="visible", timeout=2000)
    except PlaywrightTimeout:
        # 重新点击一次作为重试
        await select_input.click()
        try:
            await page.locator('.el-select-dropdown:visible').first.wait_for(state="visible", timeout=2000)
        except PlaywrightTimeout:
            pass

    # 用 JS evaluate 精准匹配并点击选项（绕过 readonly + 可见性检查的限制）
    clicked = await page.evaluate("""(args) => {
        const {option_text} = args;
        const dropdowns = document.querySelectorAll('.el-select-dropdown');
        for (const dd of dropdowns) {
            if (dd.style.display === 'none') continue;
            const items = dd.querySelectorAll('.el-select-dropdown__item');
            for (const item of items) {
                const text = item.querySelector('span') ? item.querySelector('span').textContent.trim() : item.textContent.trim();
                if (text === option_text) {
                    item.click();
                    return true;
                }
            }
        }
        return false;
    }""", {"option_text": option_text})

    if clicked:
        # 等待 Vue nextTick
        await page.evaluate("() => new Promise(r => setTimeout(r, 100))")
        print(f"  [完成] {label_text}: 已选择 '{option_text}'", file=sys.stderr)
        return True

    # 回退：用 JS 设置 input value 触发搜索过滤（fill() 对 readonly 元素无效）
    await page.evaluate("""(args) => {
        const {label_text, option_text} = args;
        const items = document.querySelectorAll('.el-form-item');
        for (const item of items) {
            const label = item.querySelector('label');
            if (label && label.textContent.includes(label_text)) {
                const input = item.querySelector('.el-select .el-input__inner');
                if (input) {
                    const proto = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value');
                    if (proto && proto.set) {
                        proto.set.call(input, option_text);
                        input.dispatchEvent(new Event('input', { bubbles: true }));
                        input.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                }
                break;
            }
        }
    }""", {"label_text": label_text, "option_text": option_text})

    # 等待搜索过滤
    await page.evaluate("() => new Promise(r => setTimeout(r, 200))")

    # 再次尝试 JS 点击
    clicked = await page.evaluate("""(args) => {
        const {option_text} = args;
        const dropdowns = document.querySelectorAll('.el-select-dropdown');
        for (const dd of dropdowns) {
            if (dd.style.display === 'none') continue;
            const items = dd.querySelectorAll('.el-select-dropdown__item');
            for (const item of items) {
                const text = item.querySelector('span') ? item.querySelector('span').textContent.trim() : item.textContent.trim();
                if (text === option_text) {
                    item.click();
                    return true;
                }
            }
        }
        return false;
    }""", {"option_text": option_text})

    if clicked:
        await page.evaluate("() => new Promise(r => setTimeout(r, 100))")
        print(f"  [完成] {label_text}: 已搜索选择 '{option_text}'", file=sys.stderr)
        return True

    # 失败时输出可用选项以便诊断
    available = await page.evaluate("""() => {
        const result = [];
        const dropdowns = document.querySelectorAll('.el-select-dropdown');
        for (const dd of dropdowns) {
            if (dd.style.display === 'none') continue;
            const items = dd.querySelectorAll('.el-select-dropdown__item');
            for (const item of items) {
                const text = item.querySelector('span') ? item.querySelector('span').textContent.trim() : item.textContent.trim();
                if (text) result.push(text);
            }
        }
        return result;
    }""")
    print(f"  [警告] {label_text}: 未找到选项 '{option_text}'（可用: {available[:10]}）", file=sys.stderr)
    await page.keyboard.press("Escape")
    return False


async def el_input_by_label(page, label_text: str, value: str):
    """通过 label 文本定位 el-input 并填写值。

    Args:
        page: Playwright page
        label_text: 表单标签文本，如 "组件片数"
        value: 要填写的值，如 "800"

    Returns:
        bool: 是否成功填写
    """
    form_item = await _locate_form_item(page, label_text)
    if form_item is None:
        return False

    input_el = form_item.locator('.el-input input, .el-textarea textarea').first

    if not await input_el.is_visible(timeout=3000):
        print(f"  [警告] {label_text}: 未找到输入框", file=sys.stderr)
        return False

    # 先清空再填写
    await input_el.click()
    await input_el.fill("")
    await page.evaluate("() => new Promise(r => setTimeout(r, 100))")
    await input_el.fill(value)

    # 验证填写结果（使用 evaluate 触发 Vue 响应式更新）
    await page.evaluate("() => new Promise(r => setTimeout(r, 50))")
    actual = await input_el.input_value()
    if str(actual) == str(value):
        print(f"  [完成] {label_text}: 已填写 '{value}'", file=sys.stderr)
        return True
    else:
        print(f"  [警告] {label_text}: 填写后值为 '{actual}'，期望 '{value}'", file=sys.stderr)
        return False


# ==================== 填写产品信息 ====================

async def fill_product_info(page, flow_id: str, component_power: int, component_count: int):
    """在流程详情页的产品信息区域填写数据。

    Args:
        page: Playwright page
        flow_id: 流程编号
        component_power: 单片功率（如715）
        component_count: 组件片数（如800）

    Returns:
        bool: 是否全部填写成功
    """
    # 导航到流程详情页
    url = f"{DMS_URL}/#/process/process_detail?bizFlowId={flow_id}&flowStatus=0"
    print(f"[导航] 进入流程详情页: {flow_id}", file=sys.stderr)
    await page.goto(url, timeout=20000)
    await page.wait_for_load_state("networkidle", timeout=15000)

    if is_on_login_page(page):
        await do_login(page)
        await page.goto(url, timeout=20000)
        await page.wait_for_load_state("networkidle", timeout=15000)

    # 等待产品信息区域加载（替代固定 3s 等待）
    product_title = page.locator('.row-title:has-text("产品信息")')
    try:
        await product_title.wait_for(state="visible", timeout=15000)
    except PlaywrightTimeout:
        print("[错误] 未找到产品信息区域，页面可能未正确加载", file=sys.stderr)
        return False

    print("[信息] 产品信息区域已加载", file=sys.stderr)

    # ==================== 字段填写顺序 ====================
    # 注意：某些字段有联动关系，需要按顺序填写
    # 1. 产品类型（选择后可能影响品牌等字段）
    # 2. 品牌（由产品类型联动，系统自动填充，跳过）
    # 3. 其他字段

    success_count = 0
    fields_total = 0

    # 1. 产品类型 - 必填，el-select（可能影响后续联动的可用性）
    print("\n[填写] 产品类型...", file=sys.stderr)
    fields_total += 1
    if await el_select_by_label(page, "产品类型", PRODUCT_TYPE):
        success_count += 1
    # 产品类型是联动前置字段，选择后等待 Vue nextTick 更新其他字段状态
    await page.wait_for_timeout(300)

    # 2. 品牌 - 必填，el-select（通常禁用状态，由系统自动填充，跳过）
    print("[填写] 品牌...", file=sys.stderr)
    fields_total += 1
    print("  [跳过] 品牌字段由系统自动填充", file=sys.stderr)
    success_count += 1

    # 3. 数智平台类型 - 必填，el-select
    print("[填写] 数智平台类型...", file=sys.stderr)
    fields_total += 1
    if await el_select_by_label(page, "数智平台类型", DIGITAL_PLATFORM_TYPE):
        success_count += 1

    # 4. 规格 - 必填，el-select
    print("[填写] 规格...", file=sys.stderr)
    fields_total += 1
    if await el_select_by_label(page, "规格", SPEC_DEFAULT):
        success_count += 1

    # 5. 单片功率 - 必填，el-select
    print(f"[填写] 单片功率: {component_power}W...", file=sys.stderr)
    fields_total += 1
    # 尝试选择匹配的功率
    power_value = f"{component_power}W"
    if await el_select_by_label(page, "单片功率", power_value):
        success_count += 1
    else:
        # 尝试不带W的格式
        if await el_select_by_label(page, "单片功率", str(component_power)):
            success_count += 1

    # 6. 组件片数 - 必填，el-input（唯一的手动输入框）
    print(f"[填写] 组件片数: {component_count}...", file=sys.stderr)
    fields_total += 1
    if await el_input_by_label(page, "组件片数", str(component_count)):
        success_count += 1

    # 7. 屋顶类型 - 必填，el-select
    print("[填写] 屋顶类型...", file=sys.stderr)
    fields_total += 1
    if await el_select_by_label(page, "屋顶类型", ROOF_TYPE):
        success_count += 1

    # 8. 安装方式 - 必填，el-select
    print("[填写] 安装方式...", file=sys.stderr)
    fields_total += 1
    if await el_select_by_label(page, "安装方式", INSTALL_METHOD):
        success_count += 1

    # 9. 排数 - 必填，el-select
    print("[填写] 排数...", file=sys.stderr)
    fields_total += 1
    if await el_select_by_label(page, "排数", ROW_COUNT):
        success_count += 1

    # 10. 备注 - el-textarea（产品信息区域内的备注，与其他字段统一用 _locate_form_item 定位）
    print(f"[填写] 备注: {REMARK_TEXT}...", file=sys.stderr)
    fields_total += 1
    try:
        form_item = await _locate_form_item(page, "备注")
        if form_item:
            remark_input = form_item.locator('.el-textarea textarea, .form-item-ui-textarea textarea').first
            if await remark_input.is_visible(timeout=1000):
                await remark_input.click()
                await remark_input.fill(REMARK_TEXT)
                # 触发 Vue 响应式事件
                await remark_input.evaluate("""el => {
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                    el.dispatchEvent(new Event('blur', { bubbles: true }));
                }""")
                await page.evaluate("() => new Promise(r => setTimeout(r, 50))")
                actual = await remark_input.input_value()
                if actual == REMARK_TEXT:
                    print(f"  [完成] 备注: 已填写", file=sys.stderr)
                    success_count += 1
                else:
                    print(f"  [警告] 备注: 填写后值为 '{actual}'", file=sys.stderr)
            else:
                print("  [警告] 备注: 未找到输入框", file=sys.stderr)
    except Exception as e:
        print(f"  [异常] 备注: {e}", file=sys.stderr)

    # 结果汇总
    print(f"\n[完成] 产品信息填写完成: {success_count}/{fields_total} 个字段成功", file=sys.stderr)

    if success_count < fields_total:
        print("[提示] 部分字段填写失败，请手动检查并补充", file=sys.stderr)

    print("[提示] 请手动确认信息无误后，点击审批按钮", file=sys.stderr)
    return success_count == fields_total


# ==================== 主流程 ====================

async def run(args, browser_manager=None):
    """运行产品信息填写流程。

    Args:
        args: 命令行参数
        browser_manager: 可选的共享浏览器管理器实例。如果提供，则复用该管理器的浏览器和登录状态。
    """
    print(f"\n=== 产品信息填写 ===\n", file=sys.stderr)

    # 判断是否使用共享浏览器管理器
    use_shared = browser_manager is not None

    if use_shared:
        # 使用共享浏览器管理器（被工作流调用）
        manager = browser_manager
        page = await manager.get_page()
        await manager.ensure_logged_in(page)

        try:
            await fill_product_info(
                page,
                args.flow_id,
                args.component_power,
                args.component_count,
            )

            # 被工作流调用时，不等待、不关闭浏览器，直接返回
            # 浏览器保持打开状态，由工作流统一管理

        except Exception as e:
            print(f"[错误] {e}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
    else:
        # 独立启动 Chromium（通过 subprocess 脱离 Playwright 生命周期控制）
        import socket, subprocess, json, urllib.request, time
        from pathlib import Path
        _user_data_dir = Path.home() / ".dms_browser_data"
        _user_data_dir.mkdir(parents=True, exist_ok=True)

        # 找到 Playwright 安装的 Chromium 可执行文件
        _browsers_base = os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or os.path.expanduser("~\\AppData\\Local\\ms-playwright")
        _chromium_path = None
        if os.path.isdir(_browsers_base):
            for _d in sorted(os.listdir(_browsers_base), reverse=True):
                if _d.startswith("chromium-"):
                    _exe = os.path.join(_browsers_base, _d, "chrome-win64", "chrome.exe")
                    if os.path.isfile(_exe):
                        _chromium_path = _exe
                        break
        if not _chromium_path:
            raise RuntimeError("找不到 Chromium 浏览器，请运行 playwright install chromium")

        # 找空闲端口
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as _s:
            _s.bind(("", 0))
            _debug_port = _s.getsockname()[1]

        # 启动 Chromium（独立进程，父进程退出不影响它）
        _cmd = [
            _chromium_path,
            f"--remote-debugging-port={_debug_port}",
            f"--user-data-dir={str(_user_data_dir)}",
            "--no-first-run",
            "--no-default-browser-check",
        ]
        if not args.headless:
            _cmd.append("--start-maximized")
        else:
            _cmd.append("--headless")

        _chrome_proc = subprocess.Popen(
            _cmd,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print(f"[浏览器] Chromium 已启动 (PID: {_chrome_proc.pid})", file=sys.stderr)

        # 等待 CDP 端点就绪
        _ws_url = None
        for _ in range(60):
            try:
                _req = urllib.request.urlopen(f"http://127.0.0.1:{_debug_port}/json/version", timeout=1)
                _data = json.loads(_req.read().decode())
                _ws_url = _data.get("webSocketDebuggerUrl")
                if _ws_url:
                    break
            except Exception:
                pass
            time.sleep(0.5)

        if not _ws_url:
            _chrome_proc.kill()
            raise RuntimeError("浏览器启动超时")

        print("[浏览器] CDP 已连接", file=sys.stderr)

        # 通过 CDP 连接 Playwright（Chromium 独立运行，断开连接不影响它）
        p = await async_playwright().start()
        browser = await p.chromium.connect_over_cdp(_ws_url)
        _context = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = _context.pages[0] if _context.pages else await _context.new_page()

        try:
            # 1. 登录
            await page.goto(DMS_URL)
            await page.wait_for_load_state("networkidle", timeout=15000)
            if is_on_login_page(page):
                await do_login(page)
            else:
                print("[登录] 会话有效", file=sys.stderr)

            # 2. 填写产品信息（组件）
            await fill_product_info(
                page,
                args.flow_id,
                args.component_power,
                args.component_count,
            )

            # 3. 输出完成信息
            print("=" * 50, file=sys.stderr)
            print("  \u2705 产品信息已填写完成", file=sys.stderr)
            print("  请在浏览器中确认信息无误", file=sys.stderr)
            print("  确认后手动点击审批按钮", file=sys.stderr)
            print("=" * 50, file=sys.stderr)

            if not args.headless:
                if sys.stdin.isatty():
                    print("[等待] 浏览器窗口保持打开，审批完成后在此终端按 Enter 退出...", file=sys.stderr)
                    sys.stdout.flush()
                    sys.stderr.flush()
                    try:
                        await asyncio.get_running_loop().run_in_executor(None, input)
                    except EOFError:
                        print("[信息] stdin 已关闭，直接退出", file=sys.stderr)
                else:
                    print("[信息] 非交互式终端，脚本直接退出，浏览器保持打开", file=sys.stderr)

        except Exception as e:
            print(f"[错误] {e}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)

        finally:
            if args.headless:
                print("[清理] 关闭浏览器...", file=sys.stderr)
                try:
                    _chrome_proc.kill()
                    _chrome_proc.wait(timeout=5)
                except Exception:
                    pass
                print("[清理] 完成", file=sys.stderr)
            else:
                print(f"[清理] 浏览器保持打开（PID: {_chrome_proc.pid}），请手动审批后关闭浏览器窗口", file=sys.stderr)
                print("[清理] 跳过浏览器关闭（非无头模式，浏览器进程已脱离脚本控制）", file=sys.stderr)

            # 断开 Playwright 连接（Chromium 是独立进程，不受影响）
            try:
                await p.stop()
            except Exception:
                pass
def main():
    parser = argparse.ArgumentParser(description="DMS产品信息填写工具（Element UI版）")
    parser.add_argument("--flow-id", required=True, help="流程编号")
    parser.add_argument("--component-power", type=int, required=True, help="单片功率（如715）")
    parser.add_argument("--component-count", type=int, required=True, help="组件片数（如800）")
    parser.add_argument("--headless", action="store_true", help="无头模式")
    args = parser.parse_args()

    asyncio.run(run(args))


if __name__ == "__main__":
    main()
