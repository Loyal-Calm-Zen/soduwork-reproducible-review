# SoduWork 实测复现：订单修复与工作流审查

本文评测项目用一份 Python CSV 订单汇总脚本，观察 AI 自测、外部复核、返修与人工验收如何衔接。首轮候选通过了原有 16 项测试，却把一笔应为 `1.00` 元的订单算成了 `1.01` 元；最终版修正了乘法阶段的 Decimal 精度，并补上能识别旧版错误的回归测试。

仓库保存评测使用的代码、规范、虚构输入和测试，以及另一组四节点工作流夹具。SoduWork 产品源码与安装说明见[官方仓库](https://github.com/mdiri-ai/SoduWork)。

## 运行全部代码检查

建议使用 Python 3.12 或更高版本，仅使用标准库，无须安装第三方包。本次发布前的完整复现使用 Python 3.14.7；原评测中的应用内解释器为 Python 3.12.15。

```bash
git clone https://github.com/Loyal-Calm-Zen/soduwork-reproducible-review.git
cd soduwork-reproducible-review
python3 -B code/reproduce.py
```

命令退出码应为 `0`，终端摘要中的 `successful` 应为 `true`。每次运行在 `code/verification/reader-runs/` 中新建目录，保存命令、退出状态、原始输出、结果 JSON 和文件摘要。使用 `--run-name` 指定名称时，须选一个尚不存在的目录名。

| 检查组 | 来源 | 最终版预期 |
| --- | --- | --- |
| 原始验收 | 测评侧预先冻结的黑盒 CLI 与文件协议测试 | 16/16 个方法通过，包含 19 次候选调用 |
| 外部补充 | 缺文件、分别缺少三个必需表头、输入不变 | 5/5 项通过 |
| 规范补充 | ID 大小写、输出字段与顺序、接近半分的长小数 | 3/3 项通过 |
| 产品新增回归 | SoduWork 在返修时新增的精度测试 | 5/5 个方法通过 |
| 固定样例 | 8 行虚构订单 | 4 条有效、4 条拒绝，总额 `57.31` |

这些测试集按来源分开报告。完整规范在 [code/SPEC.md](code/SPEC.md)，运行入口在 [code/reproduce.py](code/reproduce.py)。

## 对照旧版的 1 分误差

旧候选已使用 `Decimal`，但乘法仍受默认上下文精度影响。输入单价 `1.004999999999999999999999999999` 略小于 `1.005`，按规范量化到两位小数应为 `1.00`。旧版先在乘法中丢失末尾有效数字，随后得到 `1.01`。

在仓库根目录分别执行以下命令。输出目录名仅用于本次复现，再次运行时请换新名称，以免覆盖已有产物。

```bash
python3 -B verification/runs/product-round-1/candidate.py \
  --input verification/runs/product-round-1/contract-checks/decimal_just_below_half_cent/input.csv \
  --output-dir reproduction-reader-precision-old

python3 -B code/candidate.py \
  --input verification/runs/product-round-1/contract-checks/decimal_just_below_half_cent/input.csv \
  --output-dir reproduction-reader-precision-final
```

| 候选 | `summary.json` 中的 `total_amount` |
| --- | --- |
| 首轮修正版 | `"1.01"` |
| 最终版 | `"1.00"` |

两条命令都能正常完成。需要比较输出金额，才能看出旧版的问题。最终版 `code/candidate.py` 的 SHA-256 为：

```text
4b4ef9e41ef59a5ebef7a987a422a7979e9016bef9ddea4ec510d0bb88906355
```

## 四节点工作流夹具

`workflow/order-evidence.soduwork-plugin-draft.json` 是测评侧编写并导入 SoduWork 的个人工作流，依次执行：

1. 整理原始订单证据与短报告。
2. 由 `ai_review` 节点读取文件，输出审查记录和决定文件。
3. 进入 `human_review`，等待使用者检查产物并确认。
4. 由 `publish` 节点办结本机流程。

这部分需要 SoduWork 桌面端以及可用的 Pi 和模型配置；Python 复现命令只运行 CSV 代码检查。文章中的界面测试使用 SoduWork Global 1.13.13、Pi 与界面所选 `deepseek-v4.1-flash-1017`。

按以下步骤运行，每轮使用同一插件版本、底座、模型和调试说明：

1. 打开“插件 → 添加插件 → 导入插件”，选择夹具 JSON，通过预检后选择“仅安装”。
2. 新建一个不关联需求的普通会话，选择 Pi、上述模型及默认权限，使用新会话的空工作目录。
3. 输入 `/调试插件`，选择“作者夹具·订单证据审查 · v0.1.0”，将下表中某个输入文件的全文粘到“虚构订单证据 JSON”参数框；直接粘 JSON，不填文件路径，也不加参数外壳。
4. 调试说明统一填写“按本轮输入执行，审查后等待平台安排的人审。”取消“带入当前会话文字和附件”，不附加其他文件，再开始本机调试。
5. 如出现终端命令授权请求，选择拒绝，继续按夹具约定使用文件工具。原 A/B/B2 三轮都曾出现终端请求并由测评侧拒绝，人工介入应一并记录。
6. A 若停在审查节点，先保存文件与节点状态，再停止调试；B、B2 分别新建普通会话，从相同步骤开始。不要在 A 的恢复或重试入口替换输入。

| 输入文件 | 要检查的现象 |
| --- | --- |
| [A-missing-orders.json](workflow/inputs/A-missing-orders.json) | `orders` 为空，主张缺少订单支撑；查看审查决定及后续节点是否暂停 |
| [B-complete-orders.json](workflow/inputs/B-complete-orders.json) | 两笔订单为 `24.60` 和 `2.90`，合计 `27.50`；查看是否进入人工确认 |
| [B2-complete-orders-single-line.json](workflow/inputs/B2-complete-orders-single-line.json) | 与 B 语义相同的单行 JSON，用于另一次同条件运行 |

检查当前轮的 `input-evidence.json`、`report.md`、`review-notes.md` 和 `review-decision.json` 后，再决定是否点击“确认通过并继续”。原实测中 A 暂停，B/B2 均等待人工确认后办结；A 的 C4 还出现过扩张规则的判断，因此逐项理由也需要阅读。

夹具保留导入前的原始字节，`description` 中“尚未实测”是制作时的描述。上述 A/B/B2 是其后的实际运行记录。插件内两个 AI 节点使用独立执行上下文，原测试采用相同底座与模型；新模型运行时的文本和审查判断应重新检查。

## 文件布局

```text
code/
  candidate.py                   最终候选
  starter.py                     含预设缺陷的起点
  SPEC.md                        固定规范
  sample_orders.csv              8 行固定样例
  acceptance_tests.py            原 16 项验收
  near_half_regression.py        产品新增 5 项回归
  reproduce.py                   四组检查与样例复现入口
  verification/
    supplemental_checks.py       外部 5 项补充
    contract_checks.py           外部 3 项规范检查
verification/runs/product-round-1/
  candidate.py                   首轮候选
  contract-checks/decimal_just_below_half_cent/input.csv
workflow/
  order-evidence.soduwork-plugin-draft.json
  inputs/                        A/B/B2 虚构输入
```

`starter.py` 的缺陷由测评侧预设；最终候选和新增回归来自 SoduWork 内 Pi 的实际修复；原始验收、外部检查与复现封装由测评侧编写。订单均为虚构数据。运行生成的记录会包含当前工作目录，已通过 `.gitignore` 排除；分享运行结果时可先检查这些路径信息。
