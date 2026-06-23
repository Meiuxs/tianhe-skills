"""API 响应数据的解析与 FlowRecord 填充。

从 dms_browser.py 拆分而来，包含：
  - parse_json_date: 将 detail['jsonDate'] 从 JSON 字符串解析为 dict
  - mask_salesperson: 对业务员信息进行脱敏处理
  - fill_record_from_api: 从 flowDetails API 响应数据中填充 FlowRecord
  - fill_approval_from_nodes: 从 API nodeList 填充审批信息
  - fill_record_from_html: 从 HTML 页面解析字段（回退方案）
  - fill_approval_from_dict: 从审批解析结果 dict 填充到 FlowRecord
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger("dms_report")


def parse_json_date(detail: dict) -> None:
    """将 detail['jsonDate'] 从 JSON 字符串解析为 dict（如需要）。"""
    json_date_str = detail.get("jsonDate", "")
    if isinstance(json_date_str, str) and json_date_str:
        try:
            detail["jsonDate"] = json.loads(json_date_str)
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning("jsonDate 解析失败: %s", e)


def mask_salesperson(s: str) -> str:
    """对业务员信息进行脱敏处理。

    只显示姓名首字 + 工号后4位，例如 "张三(G0001)" → "张***(G001)"。
    """
    if not s or s == "--":
        return "--"
    if "(" in s:
        name_part, no_part = s.split("(", 1)
        no_part = no_part.rstrip(")")
        return f"{name_part[0]}***({no_part[-4:]})" if len(no_part) > 4 else f"{name_part[0]}***({no_part})"
    return s[0] + "***" if len(s) > 1 else s


def fill_record_from_api(rec, api_data: dict, flow_id: str) -> None:
    """从 flowDetails API 响应数据中填充 FlowRecord。

    解析 jsonDate.req（项目信息）、jsonDate.projectManagementPricing（定价）、nodeList（审批链）。
    """
    from core.html_parser import split_agent

    json_date = api_data.get("jsonDate") or {}
    if not isinstance(json_date, dict):
        logger.warning("api_data['jsonDate'] 不是 dict，使用空字典: flow_id=%s", flow_id)
        json_date = {}

    req = json_date.get("req") or {}
    if not isinstance(req, dict):
        logger.warning("jsonDate.req 不是 dict，类型=%s: flow_id=%s", type(req).__name__, flow_id)
        req = {}

    rec.project_name = req.get("projectName") or "--"

    customer_no = req.get("customerNo") or ""
    customer_name = req.get("customerName") or ""
    if customer_no and customer_name:
        rec.agent_code = customer_no
        _, rec.agent_name = split_agent(customer_name)
    elif customer_name:
        rec.agent_code = "--"
        rec.agent_name = customer_name
    else:
        rec.agent_code = "--"
        rec.agent_name = "--"

    rec.province = req.get("provincialCompanyName") or "--"

    salesman_no = req.get("salesmanNo") or ""
    salesman_name = req.get("salesmanName") or ""
    if salesman_no and salesman_name and salesman_name != "--":
        rec.salesperson = f"{salesman_name}({salesman_no})"
    elif salesman_name and salesman_name != "--":
        rec.salesperson = salesman_name
    else:
        rec.salesperson = "--"

    pricing = json_date.get("projectManagementPricing") or {}
    if isinstance(pricing, str):
        try:
            pricing = json.loads(pricing)
        except (json.JSONDecodeError, TypeError):
            pricing = {}
    if isinstance(pricing, dict):
        watt_price = pricing.get("wattUnitPrice")
        rec.unit_price = str(watt_price) if watt_price is not None else "--"
        total_price = pricing.get("totalPrice")
        rec.total_price = str(total_price) if total_price is not None else "--"
    else:
        rec.unit_price = "--"
        rec.total_price = "--"

    node_list = api_data.get("nodeList") or []
    fill_approval_from_nodes(rec, node_list)

    # 流程状态：从 jsonDate.statusName 获取
    rec.flow_status = json_date.get("statusName") or "--"

    logger.debug(
        "API flow_id=%s | project=%r | province=%r | salesman=%r | price=%.2f/%s | pricing_keys=%s",
        flow_id,
        req.get("projectName") or "--",
        req.get("provincialCompanyName") or "--",
        mask_salesperson(rec.salesperson),
        float(pricing.get("wattUnitPrice") or 0) if isinstance(pricing, dict) else 0,
        rec.total_price,
        list(pricing.keys()) if isinstance(pricing, dict) else [],
    )


def fill_approval_from_nodes(rec, node_list: list) -> None:
    """从 API nodeList 填充审批信息。"""
    submit_time = "--"
    negotiation_processor = "--"
    negotiation_status = "--"
    negotiation_time = "--"
    province_processor = "--"
    province_status = "--"
    final_approval_time = "--"

    for node in node_list:
        role_name = node.get("roleName") or ""
        user_name = node.get("uname") or node.get("userName") or "--"
        status_name = node.get("statusName") or "--"
        update_time = node.get("updateTime") or "--"

        if "流程发起人" in role_name and "提交审核" in status_name:
            submit_time = update_time
        elif "项目管理部核价" in role_name:
            negotiation_processor = user_name
            negotiation_status = status_name
            negotiation_time = update_time
        elif "省总" in role_name or "省公司" in role_name:
            province_processor = user_name
            province_status = status_name
        elif "采购" in role_name or "商务" in role_name:
            # 已废弃，保留供后续恢复使用
            pass

        if "通过" in status_name and update_time and update_time not in ("--", ""):
            if final_approval_time in ("--", "") or update_time > final_approval_time:
                final_approval_time = update_time

    rec.submit_time = submit_time
    rec.negotiation_processor = negotiation_processor
    rec.negotiation_status = negotiation_status
    rec.negotiation_time = negotiation_time
    rec.province_processor = province_processor
    rec.province_status = province_status
    rec.final_approval_time = final_approval_time
    # 计算是否有效：项目管理部核价审批通过即为有效
    rec.is_valid = "是" if negotiation_status and "通过" in negotiation_status else "否"


def fill_record_from_html(rec, html: str) -> None:
    """从 HTML 页面解析字段（回退方案）。"""
    from core.html_parser import extract_from_html, split_agent

    rec.project_name = extract_from_html(html, "项目名称")
    agent_raw = extract_from_html(html, "代理商")
    rec.agent_code, rec.agent_name = split_agent(agent_raw)
    rec.province = extract_from_html(html, "省公司")
    rec.salesperson = extract_from_html(html, "业务员")
    rec.unit_price = extract_from_html(html, "瓦单价(元/瓦)")
    rec.total_price = extract_from_html(html, "总价(元)")


def fill_approval_from_dict(rec, approval: dict) -> None:
    """从审批解析结果 dict 填充到 FlowRecord。"""
    rec.submit_time = approval.get("submit_time", "--")
    rec.negotiation_processor = approval.get("negotiation_processor", "--")
    rec.negotiation_status = approval.get("negotiation_status", "--")
    rec.negotiation_time = approval.get("negotiation_time", "--")
    rec.province_processor = approval.get("province_processor", "--")
    rec.province_status = approval.get("province_status", "--")
    rec.final_approval_time = approval.get("final_approval_time", "--")
    # 计算是否有效：项目管理部核价审批通过即为有效
    negotiation_status = approval.get("negotiation_status", "--")
    rec.is_valid = "是" if negotiation_status and "通过" in negotiation_status else "否"
