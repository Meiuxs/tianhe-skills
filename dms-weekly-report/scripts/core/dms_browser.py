"""DMS 浏览器自动化模块（薄封装入口）。

保留所有公开 API 和 re-export 兼容层，具体实现拆分到：
  - core.filtering: 流程筛选的 DOM 操作
  - core.html_parser: HTML 页面解析与 BOM 提取
  - core.api_parser: API 响应数据的解析与 FlowRecord 填充
  - core.detail_extractor: 单条询价详情提取的编排层
"""

from __future__ import annotations

import asyncio
import functools
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from urllib.parse import urlparse, parse_qs

from column_definitions import (
    DMS_URL, LOGIN_CHECK_DOMAIN,
    NAV_TIMEOUT, LOAD_TIMEOUT, WAIT_SHORT, WAIT_MEDIUM,
    MAX_RETRIES, RETRY_BASE_DELAY,
    TARGET_FLOW_TYPE, FILTER_PAGE_SIZE, API_FILTER_PAGE_SIZE,
    DMS_FLOW_LIST_API,
    FLOW_ID_PATTERN,
)
from dms_credentials import get_credentials as _get_dms_credentials, source_label
from playwright.async_api import (
    Page,
    BrowserContext,
    TimeoutError as PlaywrightTimeout,
)

# 新模块导入（用于 re-export 兼容层）
from core import filtering as _filtering_mod
from core import html_parser as _html_parser_mod
from core import api_parser as _api_parser_mod
from core import detail_extractor as _detail_extractor_mod
from core._utils import retry_async  # 从独立模块导入，避免循环依赖

logger = logging.getLogger("dms_report")

# ==================== 公开 API ====================
__all__ = [
    # 数据类
    "FlowRecord",
    "TableProcessResult",
    # 登录
    "is_on_login_page",
    "ensure_logged_in",
    "do_login",
    # Token
    "get_access_token",
    # 筛选
    "filter_and_get_flow_ids",
    "filter_and_get_flow_ids_via_api",
    "get_week_range",
    # 提取
    "extract_detail_by_url",
    "extract_all_parallel",
    # 重试
    "retry_async",
    # 常量
    "API_FILTER_PAGE_SIZE",
]

# ==================== 选择器常量 ====================
# 关键 DOM 选择器集中管理，前端改动时只需修改此处
SELECTORS: dict[str, str] = {
    "date_start": "input[placeholder='开始时间']",
    "date_end": "input[placeholder='结束时间']",
    "flow_type_dropdown": "input[placeholder='请选择流程类型']",
    "pagination": ".el-pager",
    "table_body": "table.el-table__body",
    "table_tbody": "table.el-table__body tbody",
    "total_records": "text=/共.*条记录/",
}

# ==================== 数据类 ====================


@dataclass
class FlowRecord:
    """提取到的单条询价记录——最终写入 Excel 的一行数据。"""
    flow_id: str = ""
    project_name: str = "--"
    agent_code: str = "--"
    agent_name: str = "--"
    province: str = "--"
    salesperson: str = "--"
    module_kw: float | None = None
    inverter_kw: float | None = None
    battery_kwh: float | None = None
    unit_price: str = "--"
    total_price: str = "--"
    submit_time: str = "--"
    remark: str = "无"
    ordered: str = "否"                    # TODO: 后续可能恢复使用
    is_valid: str = "否"                  # 是否有效：项目管理部核价审批通过为"是"
    negotiation_processor: str = "--"      # 项目管理部核价审批人
    negotiation_status: str = "--"        # 项目管理部核价审批状态
    negotiation_time: str = "--"          # 项目管理部核价审批时间
    province_processor: str = "--"
    province_status: str = "--"
    purchase_processor: str = "--"        # TODO: 后续可能恢复使用
    purchase_status: str = "--"           # TODO: 后续可能恢复使用
    final_approval_time: str = "--"
    flow_status: str = "--"               # 流程状态（如审批通过、作废等）


@dataclass
class TableProcessResult:
    """表格翻页处理结果。"""
    flow_ids: list[str] = field(default_factory=list)
    seen_ids: set[str] = field(default_factory=set)
    skipped_wrong_type: int = 0
    skipped_invalid: int = 0
    skipped_dup: int = 0
    flow_status_map: dict[str, str] = field(default_factory=dict)  # flow_id → statusName

    @property
    def valid_rows(self) -> int:
        """有效行数（即已添加的流程编号数量）。"""
        return len(self.flow_ids)

    def add_flow_id(self, flow_id: str) -> bool:
        """添加流程编号，自动同步 seen_ids 去重。

        Returns:
            True 如果成功添加（此前未见过），False 如果是重复。
        """
        if flow_id in self.seen_ids:
            return False
        self.seen_ids.add(flow_id)
        self.flow_ids.append(flow_id)
        return True


# ==================== 工具函数 ====================


def is_on_login_page(url: str) -> bool:
    """判断当前 URL 是否为登录页面。"""
    return LOGIN_CHECK_DOMAIN in url


async def ensure_logged_in(page: Page, target_url: str) -> None:
    """如果当前在登录页面则自动登录，然后导航到目标 URL。

    若当前已在目标页面上则跳过，避免不必要的导航。

    URL 匹配策略：
      1. 完全相等 → 跳过
      2. scheme+netloc+path 相同 → 视为同一页面，跳过（容忍查询参数差异）
      3. 详情页（含 bizFlowId）→ 仅比较 bizFlowId 参数值
      4. 其他情况 → 导航
    """
    if is_on_login_page(page.url):
        await do_login(page)

    # 完全相等
    if page.url == target_url:
        return

    current = urlparse(page.url)
    target = urlparse(target_url)

    # scheme+netloc+path 相同时视为同一页面（如分页、筛选参数变化不影响页面身份）
    if current.scheme == target.scheme and current.netloc == target.netloc and current.path == target.path:
        # 详情页需进一步校验 bizFlowId
        if "bizFlowId" in target_url:
            target_params = parse_qs(target.query)
            current_params = parse_qs(current.query)
            target_flow_id = target_params.get("bizFlowId", [None])[0]
            current_flow_id = current_params.get("bizFlowId", [None])[0]
            if target_flow_id and current_flow_id and target_flow_id == current_flow_id:
                return
            # bizFlowId 不一致，需要导航
        else:
            # 非详情页，路径相同即视为已在目标页面
            return

    # 需要导航
    await page.goto(target_url, timeout=NAV_TIMEOUT)
    await page.wait_for_load_state("networkidle", timeout=LOAD_TIMEOUT)


async def get_access_token(context: BrowserContext) -> str | None:
    """从浏览器 cookie 中提取 DMS 的 access_token。

    登录后 DMS 系统会在 cookie 中设置 dms_admin_token，
    该 token 用于后端 API 调用的 Authorization 头。

    Args:
        context: Playwright BrowserContext

    Returns:
        access_token 字符串，未登录或无 cookie 时返回 None。
    """
    cookies = await context.cookies()
    for c in cookies:
        if c["name"] == "dms_admin_token":
            return c["value"]
    return None

# 模块级 token 缓存，避免每次 API 请求都重新读取 cookie
# 带 TTL：token 缓存超过 TTL 后自动刷新，避免 token 过期后仍使用旧值
_cached_token: str | None = None
_cached_token_time: float = 0.0  # asyncio.get_event_loop().time() 时间戳
_TOKEN_CACHE_TTL = 300  # token 缓存 TTL（秒），5 分钟


async def _get_api_headers(context: BrowserContext) -> dict[str, str] | None:
    """获取 API 请求的 Authorization header（带缓存 + TTL）。"""
    global _cached_token, _cached_token_time
    now = asyncio.get_event_loop().time()
    if _cached_token is None or (now - _cached_token_time) > _TOKEN_CACHE_TTL:
        _cached_token = await get_access_token(context)
        _cached_token_time = now
    if _cached_token:
        return {"Authorization": f"bearer {_cached_token}"}
    return None


async def filter_and_get_flow_ids_via_api(
    context: BrowserContext, start_date: str, end_date: str,
    include_invalid: bool = True,
) -> TableProcessResult:
    """通过 API 筛选已办流程，返回有效流程编号列表。

    替代页面 DOM 解析的纯 API 方案，避免选择器失效和 HTML 重复行问题。

    DMS 列表 API: POST /dms-admin/newFlow/newFlowList
      - startTime / endTime: 日期范围（YYYY-MM-DD）
      - flowStatus: 1=已办
      - pageNum / pageSize: 分页参数

    响应结构: {"code":1,"data":{"total":N,"records":[...]}}
    记录字段: bizFlowId, flowName, statusName, createName, createOrg 等
    """
    logger.info("API 筛选日期范围: %s ~ %s", start_date, end_date)
    headers = await _get_api_headers(context)
    if not headers:
        logger.warning("未获取到 access_token，API 筛选不可用")
        return TableProcessResult()

    result = TableProcessResult()
    page_num = 1

    while True:
        try:
            resp = await context.request.post(
                DMS_FLOW_LIST_API,
                data={
                    "startTime": start_date,
                    "endTime": end_date,
                    "pageNum": page_num,
                    "pageSize": API_FILTER_PAGE_SIZE,
                    "flowStatus": 1,
                },
                headers=headers,
                timeout=NAV_TIMEOUT,
            )
            if not resp.ok:
                logger.error("API 筛选请求失败: HTTP %d", resp.status)
                break
            body = await resp.json()
        except Exception as e:
            logger.error("API 筛选请求异常: %s", e)
            break

        if body.get("code") != 1:
            logger.warning("API 筛选返回异常: %s", body.get("errMsg", ""))
            break

        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, dict):
            logger.warning("API 筛选响应格式异常: %s", json.dumps(body, ensure_ascii=False)[:500])
            break

        total = data.get("total", 0)
        rows = data.get("records") or []
        logger.info("API 筛选第 %d 页: 获取 %d 条（总计 %d 条）", page_num, len(rows), total)

        if not rows:
            break

        for row in rows:
            flow_id = str(row.get("bizFlowId") or row.get("flowId") or "")
            flow_name = str(row.get("flowName") or "")
            status_name = str(row.get("statusName") or "")

            # 流程编号校验
            if not re.match(FLOW_ID_PATTERN, flow_id):
                continue

            # 流程类型校验（通过 flowName 匹配）
            if TARGET_FLOW_TYPE not in flow_name:
                result.skipped_wrong_type += 1
                continue

            # 作废校验
            if "作废" in status_name:
                result.skipped_invalid += 1
                if not include_invalid:
                    continue

            # 去重
            if flow_id in result.seen_ids:
                result.skipped_dup += 1
                continue

            result.add_flow_id(flow_id)
            result.flow_status_map[flow_id] = status_name

        # 翻页判断
        if len(result.flow_ids) >= total or len(rows) < API_FILTER_PAGE_SIZE:
            break
        page_num += 1

    logger.info("API 筛选结果: 有效 %d 个流程", len(result.flow_ids))
    if result.skipped_wrong_type:
        logger.info("  跳过非目标流程: %d 条", result.skipped_wrong_type)
    if result.skipped_invalid:
        if include_invalid:
            logger.info("  作废流程: %d 条（已包含）", result.skipped_invalid)
        else:
            logger.info("  跳过作废流程: %d 条", result.skipped_invalid)
    if result.skipped_dup:
        logger.info("  跳过重复流程: %d 条", result.skipped_dup)
    return result


def get_week_range(weeks_ago: int = 0) -> tuple[str, str]:
    """计算指定周的开始（周一）和结束日期。

    使用中国时区（Asia/Shanghai）确保周一/周日计算正确。

    注意：weeks_ago=0（本周）时，end_date 为今天（而非本周日），
    即只查询到当前日期为止的数据。weeks_ago>=1 时，end_date 为周日。

    Args:
        weeks_ago: 距离今天的周数，0 表示本周，1 表示上周。
                   不支持负数。

    Returns:
        (start_date, end_date) 字符串，格式 YYYY-MM-DD。
    """
    if weeks_ago < 0:
        raise ValueError(f"weeks_ago 必须 >= 0，收到: {weeks_ago}")
    today = datetime.now(ZoneInfo("Asia/Shanghai"))
    monday = today - timedelta(days=today.weekday()) - timedelta(weeks=weeks_ago)
    end = today if weeks_ago == 0 else monday + timedelta(days=6)
    return monday.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


def _log_credential_source(source: str) -> None:
    """记录凭据来源的回调函数（模块级，避免重复创建闭包）。"""
    logger.info("从 %s 加载登录凭据", source_label(source))


def _load_dms_credentials() -> tuple[str, str]:
    """从共享模块读取登录凭据。"""
    return _get_dms_credentials(on_source=_log_credential_source)


# ==================== 登录 ====================


@retry_async(max_retries=MAX_RETRIES)
async def do_login(page: Page) -> None:
    """自动填写登录表单并提交。"""
    try:
        username, password = _load_dms_credentials()
    except Exception as e:
        logger.error("加载 DMS 登录凭据失败: %s", e)
        raise RuntimeError("无法加载登录凭据，请检查 dms_credentials.json") from e

    logger.info("正在登录...")
    await page.wait_for_selector("#form_item_account", state="visible", timeout=NAV_TIMEOUT)
    await page.locator("#form_item_account").fill(username)
    await page.locator("#form_item_password").fill(password)
    del password
    await page.get_by_role("button", name="登 录").click()
    try:
        await page.wait_for_url(f"{DMS_URL}/**", timeout=NAV_TIMEOUT)
        await page.wait_for_load_state("networkidle", timeout=LOAD_TIMEOUT)
        masked = username[:3] + "***" + (username[username.index("@"):] if "@" in username else "")
        logger.info("登录成功 (%s)", masked)
    except PlaywrightTimeout:
        if is_on_login_page(page.url):
            raise RuntimeError("登录失败，请检查账号密码")


# ==================== 筛选 ====================


async def filter_and_get_flow_ids(page: Page, start_date: str, end_date: str,
                                   include_invalid: bool = True) -> TableProcessResult:
    """在已办流程中按日期筛选，返回有效流程编号列表（支持多页翻页）。"""
    logger.info("筛选日期范围: %s ~ %s", start_date, end_date)
    await _navigate_to_process_center(page)

    await page.get_by_role("menuitem", name="已办流程").click()
    await page.wait_for_timeout(WAIT_SHORT)

    # 日期输入框：fill() 会自动清空并输入，无需手动全选
    start_input = page.get_by_placeholder("开始时间")
    await start_input.click()
    await start_input.fill(start_date)

    end_input = page.get_by_placeholder("结束时间")
    await end_input.click()
    await end_input.fill(end_date)
    await page.get_by_role("button", name="查询").click()
    await page.wait_for_timeout(WAIT_MEDIUM)

    # 读取总记录数
    total_el = page.locator(SELECTORS["total_records"])
    if await total_el.count() == 0:
        logger.info("未找到分页信息，可能无记录")
        return TableProcessResult()

    total_text = await total_el.first.text_content() or ""
    total_match = re.search(r"共\s*(\d+)\s*条", total_text)
    total = int(total_match.group(1)) if total_match else 0
    logger.info("共 %d 条记录", total)
    if total == 0:
        return TableProcessResult()

    total_pages = (total + FILTER_PAGE_SIZE - 1) // FILTER_PAGE_SIZE
    logger.info("分页: %d 条/页，共 %d 页", FILTER_PAGE_SIZE, total_pages)

    result = TableProcessResult()

    # 处理第 1 页
    result = await _process_table_rows(page, result, include_invalid=include_invalid)

    # 翻页处理后续页面
    for page_num in range(2, total_pages + 1):
        logger.debug("翻到第 %d 页", page_num)
        try:
            await page.locator(SELECTORS["pagination"]).get_by_text(str(page_num), exact=True).click()
            # 等待表格新数据渲染完成，避免新旧数据重叠导致重复计数
            await page.locator(SELECTORS["table_tbody"]).first.wait_for(
                state="visible", timeout=LOAD_TIMEOUT
            )
            await page.wait_for_timeout(WAIT_MEDIUM)
        except PlaywrightTimeout:
            logger.warning("翻到第 %d 页失败，终止翻页", page_num)
            break

        result = await _process_table_rows(page, result, include_invalid=include_invalid)

    logger.info("有效行: %d 行（去重后 %d 个流程）", result.valid_rows, len(result.flow_ids))
    if result.skipped_wrong_type:
        logger.info("跳过非目标流程: %d 条", result.skipped_wrong_type)
    if result.skipped_invalid:
        if include_invalid:
            logger.info("作废流程: %d 条（已包含）", result.skipped_invalid)
        else:
            logger.info("跳过作废流程: %d 条", result.skipped_invalid)
    if result.skipped_dup:
        logger.info("跳过重复流程: %d 条", result.skipped_dup)
    return result


# ==================== re-export 兼容层 ====================
# 保持测试文件导入路径不变（_extract_from_html, _split_agent 等带下划线前缀）

extract_detail_by_url = _detail_extractor_mod.extract_detail_by_url
_extract_from_html = _html_parser_mod.extract_from_html
_split_agent = _html_parser_mod.split_agent
_extract_bom = _html_parser_mod.extract_bom
_extract_approval_info = _detail_extractor_mod.extract_approval_info
_fill_record_from_api = _api_parser_mod.fill_record_from_api
_fill_record_from_html = _api_parser_mod.fill_record_from_html
_fill_approval_from_nodes = _api_parser_mod.fill_approval_from_nodes
_fill_approval_from_dict = _api_parser_mod.fill_approval_from_dict
_parse_json_date = _api_parser_mod.parse_json_date
_mask_salesperson = _api_parser_mod.mask_salesperson
_process_table_rows = _filtering_mod._process_table_rows
_navigate_to_process_center = _filtering_mod._navigate_to_process_center


# ==================== 并行编排 ====================


async def extract_all_parallel(
    context: BrowserContext, flow_ids: list[str], workers: int,
    flow_status_map: dict[str, str] | None = None,
) -> list[FlowRecord]:
    """并行提取所有流程详情（页面池复用模式）。"""
    total = len(flow_ids)
    logger.info("并行提取 %d 条（%d 并发）...", total, workers)

    # 预创建页面池，避免每条都 new_page/close 的开销
    pages = [await context.new_page() for _ in range(min(workers, total))]
    sem = asyncio.Semaphore(workers)

    async def _extract_with_page(ctx, fid, s, pg):
        status_name = (flow_status_map or {}).get(fid, "")
        return await extract_detail_by_url(ctx, fid, s, page=pg, flow_status_name=status_name)

    tasks = [_extract_with_page(context, flow_ids[i], sem, pages[i % len(pages)])
             for i in range(total)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # 统一关闭页面池
    for pg in pages:
        try:
            await pg.close()
        except Exception:
            pass

    records: list[FlowRecord] = []
    error_count = 0
    skipped_count = 0
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.warning("[%d/%d] %s: 异常 %s", i + 1, total, flow_ids[i], result)
            error_count += 1
        elif isinstance(result, FlowRecord):
            records.append(result)
        else:
            skipped_count += 1
    logger.info("提取完成: %d/%d 条成功, %d 条异常, %d 条跳过", len(records), total, error_count, skipped_count)
    return records
