# orders_checker.py 改造设计：API 替代浏览器下单检查

## 问题

当前 `orders_checker.py` 对每条记录都要：
1. 打开新 Playwright 页面 → 导航到订单管理页
2. 默认加载半年数据（慢）
3. 输入流程编号搜索 → 等响应
4. 关页面

N 条 × 5-15 秒/条 → 50 条约 4-12 分钟。

## 方案

改为调用 DMS 后端的 `getOrderHistoryList` API，一次拉取所有订单数据，在内存中 `set` 匹配。

## API 细节

| 项目 | 值 |
|------|-----|
| 端点 | `POST https://apigw.trinablue.com/dms-admin/orderHistory/getOrderHistoryList` |
| 认证 | `Authorization: bearer <access_token>` |
| Content-Type | `application/json` |
| 请求体 | `{"createTime":"...","toCreateTime":"...","pageNum":1,"pageSize":500}` |
| 响应 | `{code:1, data:{records:[...], total:N, pages:N}}` |
| 关键字段 | `records[].bizFlowId` → 流程编号 |

Token 来源：登录后 URL 中的 `access_token` 参数。

## 日期范围扩展

订单的创建时间可能晚于询价发起时间（审批周期），因此查询终点**扩展 1 个月**：

```
API 查询范围 = [start_date, end_date + 31天]
```

## 核心逻辑

```
flow_ids_in_orders = fetch_all_biz_flow_ids(token, start_date, end_date + 31d)
for record in records:
    record.ordered = "是" if record.flow_id in flow_ids_in_orders else "否"
```

## 文件变更

| 文件 | 变更 |
|------|------|
| `core/orders_checker.py` | 重写：移除 Playwright，新增 `fetch_ordered_flow_ids` + httpx 分页调用 |
| `run_weekly_report.py` | 提取 token 传入，移除 `workers` 参数传递 |
| `tests/test_orders_checker.py` | 重写测试：Mock httpx 响应 |
| `column_definitions.py` | 增加扩展月数常量 `ORDER_CHECK_EXTEND_DAYS = 31` |

## 边界处理

- API 异常 → 重试 2 次 → 退回到 `"检查失败"` 状态
- 空响应（无订单） → 返回空 set，所有记录标记 `"否"`
- 分页 > 10 页 → 加日志告警（理论上 500 条/页 × 10 页 = 5000 条已足够）
