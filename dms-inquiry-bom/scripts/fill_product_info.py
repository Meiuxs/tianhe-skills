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
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

# 导入共享浏览器管理器
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _compat  # noqa: F401, E402
from browser_manager import BrowserManager, get_credentials

# ==================== 配置 ====================

DMS_URL = "https://dms-admin.trinapower.com"


# ==================== 登录 ====================

def is_on_login_page(page):
    return "iauth.trinapower.com" in page.url


async def do_login(page):
    username, password = get_credentials()
    print("[登录] 正在登录...", file=sys.stderr)
    await page.wait_for_selector("#form_item_account", state="visible", timeout=15000)
    await page.locator("#form_item_account").fill(username)
    await page.locator("#form_item_password").fill(password)
    await page.get_by_role("button", name="登 录").click()
    try:
        await page.wait_for_url(f"{DMS_URL}/**", timeout=15000)
        await page.wait_for_load_state("networkidle", timeout=10000)
        masked_user = username[:3] + "***" + username[username.index("@"):] if "@" in username else "***"
        print(f"[登录] 成功 ({masked_user})", file=sys.stderr)
    except PlaywrightTimeout:
        if is_on_login_page(page):
            raise RuntimeError("登录失败，请检查账号密码")


# ==================== Element UI 表单操作工具 ====================

async def el_select_by_label(page, label_text: str, option_text: str, timeout: int = 5000):
    """通过 label 文本定位 el-select 并选择指定选项。

    Args:
        page: Playwright page
        label_text: 表单标签文本，如 "产品类型"
        option_text: 要选择的选项文本，如 "非原装系统"
        timeout: 超时时间（毫秒）

    Returns:
        bool: 是否成功选择
    """
    # 定位包含该 label 的 el-form-item
    form_item = page.locator(f'.el-form-item:has(label:has-text("{label_text}"))').first

    if not await form_item.is_visible(timeout=3000):
        print(f"  [跳过] {label_text}: 表单项不可见", file=sys.stderr)
        return False

    # 检查是否禁用（检查 el-select 或内部 el-input 的 disabled 状态）
    disabled = await form_item.evaluate("""el => {
        const select = el.querySelector('.el-select');
        if (!select) return false;
        // 检查 el-select 本身
        if (select.classList.contains('is-disabled')) return true;
        // 检查内部 el-input
        const input = select.querySelector('.el-input');
        if (input && input.classList.contains('is-disabled')) return true;
        // 检查 input 元素的 disabled 属性
        const inputEl = select.querySelector('input');
        if (inputEl && inputEl.disabled) return true;
        return false;
    }""")

    if disabled:
        print(f"  [跳过] {label_text}: 已禁用（可能是联动字段，需先选择上级）", file=sys.stderr)
        return False

    # 点击 el-select 的输入框打开下拉
    select_input = form_item.locator('.el-select .el-input__inner').first
    if not await select_input.is_visible(timeout=2000):
        print(f"  [警告] {label_text}: 未找到输入框", file=sys.stderr)
        return False

    # 清除已有值（如果有）
    current_value = await select_input.input_value()
    if current_value:
        await select_input.click()
        await select_input.fill("")
        await page.wait_for_timeout(300)

    await select_input.click()
    await page.wait_for_timeout(500)

    # 等待下拉框出现
    # Element UI 的下拉框是挂载在 body 下的 .el-select-dropdown
    try:
        await page.locator('.el-select-dropdown:visible .el-select-dropdown__item').first.wait_for(
            state="visible", timeout=3000
        )
    except PlaywrightTimeout:
        # 可能需要重新点击
        await select_input.click()
        await page.wait_for_timeout(800)

    # 使用精确匹配查找选项（避免 "无" 匹配到 "前拉后拽(无平台)"）
    # 先用 JS 找到精确匹配的选项元素
    option_found = await page.evaluate(f"""() => {{
        const dropdowns = document.querySelectorAll('.el-select-dropdown');
        for (const dd of dropdowns) {{
            if (dd.style.display === 'none') continue;
            const items = dd.querySelectorAll('.el-select-dropdown__item');
            for (const item of items) {{
                const text = item.querySelector('span') ? item.querySelector('span').textContent.trim() : item.textContent.trim();
                if (text === '{option_text}') {{
                    // 返回选项的索引用于定位
                    return true;
                }}
            }}
        }}
        return false;
    }}""")

    try:
        if option_found:
            # 使用精确匹配的 xpath 点击
            option = page.locator(
                f'.el-select-dropdown:visible .el-select-dropdown__item span:text-is("{option_text}")'
            ).first
            if await option.is_visible(timeout=2000):
                await option.click()
                await page.wait_for_timeout(300)
                print(f"  [完成] {label_text}: 已选择 '{option_text}'", file=sys.stderr)
                return True

        # 回退：尝试输入搜索
        await select_input.fill(option_text)
        await page.wait_for_timeout(500)
        option = page.locator(
            f'.el-select-dropdown:visible .el-select-dropdown__item span:text-is("{option_text}")'
        ).first
        if await option.is_visible(timeout=2000):
            await option.click()
            await page.wait_for_timeout(300)
            print(f"  [完成] {label_text}: 已搜索选择 '{option_text}'", file=sys.stderr)
            return True
        else:
            print(f"  [警告] {label_text}: 未找到选项 '{option_text}'", file=sys.stderr)
            await page.keyboard.press("Escape")
            return False
    except Exception as e:
        print(f"  [异常] {label_text}: {e}", file=sys.stderr)
        await page.keyboard.press("Escape")
        return False


async def el_input_by_label(page, label_text: str, value: str, timeout: int = 5000):
    """通过 label 文本定位 el-input 并填写值。

    Args:
        page: Playwright page
        label_text: 表单标签文本，如 "组件片数"
        value: 要填写的值，如 "800"

    Returns:
        bool: 是否成功填写
    """
    form_item = page.locator(f'.el-form-item:has(label:has-text("{label_text}"))').first

    if not await form_item.is_visible(timeout=3000):
        print(f"  [跳过] {label_text}: 表单项不可见", file=sys.stderr)
        return False

    input_el = form_item.locator('.el-input input, .el-textarea textarea').first

    if not await input_el.is_visible(timeout=2000):
        print(f"  [警告] {label_text}: 未找到输入框", file=sys.stderr)
        return False

    await input_el.click()
    await input_el.fill(value)
    await page.wait_for_timeout(300)

    # 验证填写结果
    actual = await input_el.input_value()
    if str(actual) == str(value):
        print(f"  [完成] {label_text}: 已填写 '{value}'", file=sys.stderr)
        return True
    else:
        print(f"  [警告] {label_text}: 填写后值为 '{actual}'，期望 '{value}'", file=sys.stderr)
        return False


async def get_select_options(page, label_text: str):
    """获取指定 el-select 的所有选项。

    Args:
        page: Playwright page
        label_text: 表单标签文本

    Returns:
        list: 选项文本列表
    """
    form_item = page.locator(f'.el-form-item:has(label:has-text("{label_text}"))').first

    if not await form_item.is_visible(timeout=3000):
        return []

    select_input = form_item.locator('.el-select .el-input__inner').first
    if not await select_input.is_visible(timeout=2000):
        return []

    await select_input.click()
    await page.wait_for_timeout(800)

    options = await page.locator(
        '.el-select-dropdown:visible .el-select-dropdown__item'
    ).all()

    result = []
    for opt in options:
        try:
            text = await opt.text_content()
            if text and text.strip():
                result.append(text.strip())
        except:
            pass

    await page.keyboard.press("Escape")
    await page.wait_for_timeout(300)
    return result


# ==================== 填写产品信息 ====================

async def fill_product_info(page, flow_id: str, component_power: int, component_count: int,
                             inverter_power: int = None, inverter_count: int = None,
                             box_power: int = None, box_count: int = None):
    """在流程详情页的产品信息区域填写数据。

    Args:
        page: Playwright page
        flow_id: 流程编号
        component_power: 单片功率（如715）
        component_count: 组件片数（如800）
        inverter_power: 逆变器功率kW（如50），为 None 时不填写
        inverter_count: 逆变器数量，为 None 时不填写
        box_power: 并网箱功率kW（如50），为 None 时不填写
        box_count: 并网箱数量，为 None 时不填写

    Returns:
        bool: 是否全部填写成功
    """
    # 导航到流程详情页
    url = f"{DMS_URL}/#/process/process_detail?bizFlowId={flow_id}&flowStatus=0"
    print(f"[导航] 进入流程详情页: {flow_id}", file=sys.stderr)
    await page.goto(url, timeout=20000)
    await page.wait_for_load_state("networkidle", timeout=15000)
    await page.wait_for_timeout(3000)

    if is_on_login_page(page):
        await do_login(page)
        await page.goto(url, timeout=20000)
        await page.wait_for_load_state("networkidle", timeout=15000)
        await page.wait_for_timeout(3000)

    # 确认页面加载完成
    product_title = page.locator('.row-title:has-text("产品信息")')
    if not await product_title.is_visible(timeout=5000):
        print("[错误] 未找到产品信息区域，页面可能未正确加载", file=sys.stderr)
        return False

    print("[信息] 产品信息区域已加载", file=sys.stderr)

    # ==================== 字段填写顺序 ====================
    # 注意：某些字段有联动关系，需要按顺序填写
    # 1. 产品类型（选择后可能影响品牌等字段）
    # 2. 品牌（可能依赖产品类型）
    # 3. 其他字段

    success_count = 0
    total_fields = 10

    # 1. 产品类型 - 必填，el-select
    print("\n[填写] 产品类型...", file=sys.stderr)
    if await el_select_by_label(page, "产品类型", "非原装系统"):
        success_count += 1
    await page.wait_for_timeout(500)

    # 2. 品牌 - 必填，el-select（可能依赖产品类型选择后才可编辑）
    print("[填写] 品牌...", file=sys.stderr)

    # 检查品牌字段状态（禁用状态 + 当前值）
    brand_info = await page.evaluate("""() => {
        const items = document.querySelectorAll('.el-form-item');
        for (const item of items) {
            const label = item.querySelector('label');
            if (label && label.textContent.includes('品牌')) {
                const select = item.querySelector('.el-select');
                const input = select ? select.querySelector('.el-input__inner') : null;
                // 检查多种禁用状态
                const disabled = select ? (
                    select.classList.contains('is-disabled') ||
                    (select.querySelector('.el-input') && select.querySelector('.el-input').classList.contains('is-disabled')) ||
                    (input && input.disabled)
                ) : false;
                return {
                    disabled: disabled,
                    value: input ? input.value : ''
                };
            }
        }
        return {disabled: false, value: ''};
    }""")

    if brand_info["disabled"]:
        # 品牌字段已禁用，检查是否已有正确值
        if brand_info["value"] == "小型工商业":
            print(f"  [跳过] 品牌字段已禁用，当前值已为 '{brand_info['value']}'", file=sys.stderr)
            success_count += 1
        else:
            # 等待一下看是否会解锁
            print(f"  [信息] 品牌字段禁用中，当前值='{brand_info['value']}'，等待联动...", file=sys.stderr)
            await page.wait_for_timeout(2000)

            brand_info = await page.evaluate("""() => {
                const items = document.querySelectorAll('.el-form-item');
                for (const item of items) {
                    const label = item.querySelector('label');
                    if (label && label.textContent.includes('品牌')) {
                        const select = item.querySelector('.el-select');
                        const input = select ? select.querySelector('.el-input__inner') : null;
                        const disabled = select ? (
                            select.classList.contains('is-disabled') ||
                            (select.querySelector('.el-input') && select.querySelector('.el-input').classList.contains('is-disabled')) ||
                            (input && input.disabled)
                        ) : false;
                        return {
                            disabled: disabled,
                            value: input ? input.value : ''
                        };
                    }
                }
                return {disabled: false, value: ''};
            }""")

            if brand_info["disabled"]:
                if brand_info["value"]:
                    print(f"  [跳过] 品牌字段仍禁用，但已有值 '{brand_info['value']}'", file=sys.stderr)
                    success_count += 1
                else:
                    print("  [警告] 品牌字段禁用且无值，可能需要手动处理", file=sys.stderr)
            else:
                if await el_select_by_label(page, "品牌", "小型工商业"):
                    success_count += 1
    else:
        if await el_select_by_label(page, "品牌", "小型工商业"):
            success_count += 1
    await page.wait_for_timeout(500)

    # 3. 数智平台类型 - 必填，el-select
    print("[填写] 数智平台类型...", file=sys.stderr)
    if await el_select_by_label(page, "数智平台类型", "标准"):
        success_count += 1
    await page.wait_for_timeout(500)

    # 4. 规格 - 必填，el-select
    print("[填写] 规格...", file=sys.stderr)
    if await el_select_by_label(page, "规格", "无"):
        success_count += 1
    await page.wait_for_timeout(500)

    # 5. 单片功率 - 必填，el-select（不是input！）
    print(f"[填写] 单片功率: {component_power}W...", file=sys.stderr)
    # 先获取可用选项
    power_options = await get_select_options(page, "单片功率")
    if power_options:
        print(f"  [信息] 可用选项 ({len(power_options)}个): {power_options[:5]}...", file=sys.stderr)

    # 尝试选择匹配的功率
    power_value = f"{component_power}W"
    if await el_select_by_label(page, "单片功率", power_value):
        success_count += 1
    else:
        # 尝试不带W的格式
        if await el_select_by_label(page, "单片功率", str(component_power)):
            success_count += 1
    await page.wait_for_timeout(500)

    # 6. 组件片数 - 必填，el-input（唯一的手动输入框）
    print(f"[填写] 组件片数: {component_count}...", file=sys.stderr)
    if await el_input_by_label(page, "组件片数", str(component_count)):
        success_count += 1
    await page.wait_for_timeout(500)

    # 7. 屋顶类型 - 必填，el-select
    print("[填写] 屋顶类型...", file=sys.stderr)
    if await el_select_by_label(page, "屋顶类型", "无"):
        success_count += 1
    await page.wait_for_timeout(500)

    # 8. 安装方式 - 必填，el-select
    print("[填写] 安装方式...", file=sys.stderr)
    if await el_select_by_label(page, "安装方式", "无"):
        success_count += 1
    await page.wait_for_timeout(500)

    # 9. 排数 - 必填，el-select
    print("[填写] 排数...", file=sys.stderr)
    if await el_select_by_label(page, "排数", "无"):
        success_count += 1
    await page.wait_for_timeout(500)

    # 10. 备注 - el-textarea（产品信息区域内的备注，不是项目信息区域的）
    remark_text = "非标准BOM，安装产生风险渠道伙伴自行承担"
    print(f"[填写] 备注: {remark_text}...", file=sys.stderr)
    # 使用更精确的选择器：定位产品信息区域内的 textarea
    try:
        product_section = page.locator('.form-row-box:has(.row-title:has-text("产品信息"))').first
        remark_input = product_section.locator('.el-textarea textarea, .form-item-ui-textarea textarea').first
        if await remark_input.is_visible(timeout=3000):
            await remark_input.click()
            await remark_input.fill("")
            await remark_input.type(remark_text, delay=30)
            await page.wait_for_timeout(300)
            # 触发事件
            await remark_input.evaluate("""el => {
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
                el.dispatchEvent(new Event('blur', { bubbles: true }));
            }""")
            await page.wait_for_timeout(300)
            actual = await remark_input.input_value()
            if actual == remark_text:
                print(f"  [完成] 备注: 已填写 '{remark_text}'", file=sys.stderr)
                success_count += 1
            else:
                print(f"  [警告] 备注: 填写后值为 '{actual}'", file=sys.stderr)
        else:
            print("  [警告] 备注: 未找到输入框", file=sys.stderr)
    except Exception as e:
        print(f"  [异常] 备注: {e}", file=sys.stderr)

    # 11. 逆变器信息（可选）
    if inverter_power and inverter_count:
        print(f"\n[填写] 逆变器信息: {inverter_power}kW × {inverter_count}台...", file=sys.stderr)
        await page.wait_for_timeout(500)

        # 选择产品类型为逆变器（如果可编辑）
        if await el_select_by_label(page, "产品类型", "逆变器"):
            success_count += 1
            await page.wait_for_timeout(500)

        # 填写逆变器功率
        inv_power_value = f"{inverter_power}kW"
        if await el_select_by_label(page, "规格", inv_power_value):
            success_count += 1
        elif await el_select_by_label(page, "规格", str(inverter_power)):
            success_count += 1
        await page.wait_for_timeout(500)

        # 填写逆变器数量
        if await el_input_by_label(page, "组件片数", str(inverter_count)):
            # 注意: DMS 表单中逆变器数量可能复用"组件片数"字段，也可能不同
            success_count += 1
        await page.wait_for_timeout(500)

        print(f"  [信息] 逆变器信息填写完成（{inverter_power}kW × {inverter_count}台）", file=sys.stderr)
    else:
        total_fields = 10  # 不增加额外计数

    # 12. 并网箱信息（可选）
    if box_power and box_count:
        print(f"\n[填写] 并网箱信息: {box_power}kW × {box_count}台...", file=sys.stderr)
        await page.wait_for_timeout(500)

        # 选择产品类型为并网箱
        if await el_select_by_label(page, "产品类型", "并网箱"):
            success_count += 1
            await page.wait_for_timeout(500)

        # 填写并网箱规格（功率）
        box_power_value = f"{box_power}kW"
        if await el_select_by_label(page, "规格", box_power_value):
            success_count += 1
        elif await el_select_by_label(page, "规格", str(box_power)):
            success_count += 1
        await page.wait_for_timeout(500)

        # 填写并网箱数量
        if await el_input_by_label(page, "组件片数", str(box_count)):
            success_count += 1
        await page.wait_for_timeout(500)

        print(f"  [信息] 并网箱信息填写完成（{box_power}kW × {box_count}台）", file=sys.stderr)

    # 恢复组件字段显示（如产品类型选择了"非原装系统"）
    if inverter_power or box_power:
        print('\n[恢复] 回复产品类型为"非原装系统"...', file=sys.stderr)
        if await el_select_by_label(page, "产品类型", "非原装系统"):
            await page.wait_for_timeout(500)

    # 结果汇总
    print(f"\n[完成] 产品信息填写完成: {success_count}/{total_fields} 个字段成功", file=sys.stderr)

    if success_count < total_fields:
        print("[提示] 部分字段填写失败，请手动检查并补充", file=sys.stderr)

    print("[提示] 请手动确认信息无误后，点击审批按钮", file=sys.stderr)
    return success_count == total_fields


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
            # 1. 填写产品信息（组件 + 可选逆变器/并网箱）
            await fill_product_info(
                page,
                args.flow_id,
                args.component_power,
                args.component_count,
                inverter_power=getattr(args, 'inverter_power', None),
                inverter_count=getattr(args, 'inverter_count', None),
                box_power=getattr(args, 'box_power', None),
                box_count=getattr(args, 'box_count', None),
            )

            # 2. 被工作流调用时，不等待、不关闭浏览器，直接返回
            # 浏览器保持打开状态，由工作流统一管理

        except Exception as e:
            print(f"[错误] {e}", file=sys.stderr)
            import traceback
            traceback.print_exc(file=sys.stderr)
    else:
        # 独立启动浏览器
        async with async_playwright() as p:
            try:
                browser = await p.chromium.launch(headless=args.headless, args=["--start-maximized"])
            except Exception as e:
                if args.headless:
                    print(f"[警告] 无头模式启动失败: {e}", file=sys.stderr)
                    print("[警告] 自动回退到弹出浏览器窗口模式（默认）", file=sys.stderr)
                    browser = await p.chromium.launch(headless=False, args=["--start-maximized"])
                else:
                    raise
            context = await browser.new_context(
                no_viewport=True, locale="zh-CN"
            )
            page = await context.new_page()

            try:
                # 1. 登录
                await page.goto(DMS_URL)
                await page.wait_for_load_state("networkidle", timeout=15000)
                if is_on_login_page(page):
                    await do_login(page)
                else:
                    print("[登录] 会话有效", file=sys.stderr)

                # 2. 填写产品信息（组件 + 可选逆变器/并网箱）
                await fill_product_info(
                    page,
                    args.flow_id,
                    args.component_power,
                    args.component_count,
                    inverter_power=args.inverter_power,
                    inverter_count=args.inverter_count,
                    box_power=args.box_power,
                    box_count=args.box_count,
                )

                # 3. 等待用户确认
                print("\n" + "=" * 50, file=sys.stderr)
                print("  产品信息已填写完成", file=sys.stderr)
                print("  请在浏览器中确认信息无误", file=sys.stderr)
                print("  确认后手动点击审批按钮", file=sys.stderr)
                print("=" * 50, file=sys.stderr)

                # 保持浏览器打开，等待用户操作
                if not args.headless:
                    print("\n⏳ 浏览器已保持打开，请手动检查和审批。", file=sys.stderr)
                    print("   完成后手动关闭浏览器即可。", file=sys.stderr)
                    sys.stdout.flush()
                    sys.stderr.flush()
                    # 等待浏览器被用户手动关闭
                    try:
                        while True:
                            # 检查浏览器是否仍然连接
                            try:
                                await page.evaluate("() => document.title")
                                await asyncio.sleep(1)
                            except Exception:
                                # 浏览器已关闭
                                break
                    except KeyboardInterrupt:
                        pass

            except Exception as e:
                print(f"[错误] {e}", file=sys.stderr)
                import traceback
                traceback.print_exc(file=sys.stderr)
            finally:
                await browser.close()


def main():
    parser = argparse.ArgumentParser(description="DMS产品信息填写工具（Element UI版）")
    parser.add_argument("--flow-id", required=True, help="流程编号")
    parser.add_argument("--component-power", type=int, required=True, help="单片功率（如715）")
    parser.add_argument("--component-count", type=int, required=True, help="组件片数（如800）")
    parser.add_argument("--inverter-power", type=int, default=None, help="逆变器功率kW（如50），可选")
    parser.add_argument("--inverter-count", type=int, default=None, help="逆变器数量，可选")
    parser.add_argument("--box-power", type=int, default=None, help="并网箱功率kW（如50），可选")
    parser.add_argument("--box-count", type=int, default=None, help="并网箱数量，可选")
    parser.add_argument("--headless", action="store_true", help="无头模式")
    args = parser.parse_args()

    asyncio.run(run(args))


if __name__ == "__main__":
    main()
