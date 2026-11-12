# 虚构订单 CSV 汇总：验收规范

本任务用于 SoduWork 桌面端评测，所有订单均为人工生成的虚构数据，不代表任何真实客户或业务。`starter.py` 含人工预设缺陷，用于检查修复与审查流程；这不是从真实生产事故采集的程序。

## 目标与接口

修复初始脚本，交付 `candidate.py`，仅使用 Python 3.10+ 标准库。

```bash
python3 candidate.py --input sample_orders.csv --output-dir result
```

输入文件包含 `order_id,quantity,unit_price` 三列。支持普通 UTF-8 和带 BOM 的 UTF-8，使用标准 CSV 规则解析，引号内允许逗号。字段首尾空白应去除。CSV 的第 1 行为表头，数据行的 `source_row` 从 2 开始；本任务不使用字段内换行。

## 记录规则

1. `order_id` 为非空字符串，区分大小写。去除首尾空白后判重：第一个**有效记录**保留，后续同 ID 记录拒绝。无效记录不得抢占 ID。
2. `quantity` 为非负整数，包括 0；空字段、文字、带小数点的值和负值均拒绝。
3. `unit_price` 为非负且有限的十进制数，包括 0；空字段、文字、`NaN`、正负无穷和负值均拒绝。
4. 任一字段为空时，该记录拒绝。不得将空值默认为 0。
5. 金额使用 `decimal.Decimal` 从原始十进制字符串解析和计算，不经由 `float`。
6. 每行金额 = 数量 × 输入单价，以 `ROUND_HALF_UP` 四舍五入至两位小数。总金额为**已舍入行金额之和**，也输出两位小数。例如 3 × 0.335 = 1.005，行金额为 `1.01`；三笔 1 × 0.005 的总金额为 `0.03`。
7. 无效记录独立记录原因，继续处理后续记录；包含无效行的合法 CSV 仍应成功生成报告并返回退出码 0。
8. 表头存在但无订单时，成功输出零条记录、总金额 `0.00`。输入文件不存在或缺少必需表头属于文件级错误：返回非零退出码，并向 stderr 输出可诊断说明。

## 必需输出

输出目录自动创建，成功时包含以下三份文件（UTF-8）。可增加额外解释文档，但不能改变这些文件协议。

### `summary.json`

```json
{
  "records_total": 2,
  "valid_count": 2,
  "rejected_count": 0,
  "total_amount": "45.05"
}
```

前三项为整数；`total_amount` 为恰好两位小数的字符串。满足 `records_total = valid_count + rejected_count`。

### `valid_orders.csv`

列为 `source_row,order_id,quantity,line_total`，有效记录保持输入顺序；`quantity` 输出整数，`line_total` 恰好两位小数。没有有效行时仍输出表头。

### `rejected_rows.csv`

列为 `source_row,order_id,quantity,unit_price,reason`，无效记录保持输入顺序。记录去除首尾空白的输入值，`reason` 为具体且非空的原因；不要求固定措辞。没有无效行时仍输出表头。

## 交付证据

交付代码、实际运行命令、退出码、测试输出和上述结果文件。不要仅用“已完成”“测试通过”的文字代替执行证据。说明修改了什么，哪些输入已验证，仍有哪些限制。准备材料、独立验收以及 SoduWork 内实际完成的工作需分别记录。
