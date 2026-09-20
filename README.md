# 集装箱箱号模糊识别裁决 API

基于 **Python + FastAPI + SQLite** 的 ISO 6346 集装箱箱号模糊裁决服务。接收箱号 11 个位置各自的 OCR 候选字符及置信度，在**字符类别规则、所有人代码/设备类别标识规则与模 11 校验位约束**下联合搜索，返回：

- `valid_count` —— 通过全部约束的**有效候选精确总数**（不受任何截断影响）；
- `results` —— 按**总负对数置信度** `score = -Σ ln(confidence)` 升序排列的前 20 项；同分时按完整 11 位箱号**字典序**稳定决胜；
- `status` —— `unique`（恰 1 个有效候选）/ `ambiguous`（多于 1 个）/ `invalid`（0 个）；
- 每次裁决自动落库，支持列表查询与按 ID 查询完整记录。

## 一条命令启动

```bash
docker compose up --build
```

容器启动时自动完成两件事：

1. **依赖安装** —— 镜像构建期已安装；`docker/entrypoint.sh` 启动时会幂等再确认一次（依赖缺失则自动 `pip install -r requirements.txt`）；
2. **建库** —— 执行 `python -m app.init_db`，在 SQLite 中幂等创建表与索引（`CREATE TABLE IF NOT EXISTS`）。

启动后：

| 用途 | 地址 |
| --- | --- |
| API 服务（容器内监听 `0.0.0.0:8000`） | http://localhost:8000 |
| 健康检查 | http://localhost:8000/health |
| Swagger 交互文档 | http://localhost:8000/docs |
| ReDoc 文档 | http://localhost:8000/redoc |
| OpenAPI Schema | http://localhost:8000/openapi.json |
| 裁决接口 | `POST http://localhost:8000/api/v1/adjudicate` |
| 记录列表 | `GET http://localhost:8000/api/v1/records` |
| 记录详情 | `GET http://localhost:8000/api/v1/records/{request_id}` |

宿主机端口可用环境变量 `PORT` 覆盖（默认 `8000`）：`PORT=9000 docker compose up --build`。

## 配置（环境变量）

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `DB_PATH` | `/data/adjudication.db` | SQLite 数据库文件路径，已挂载命名卷 `adjudication-data` 持久化 |
| `HOST` | `0.0.0.0` | 监听地址 |
| `PORT` | `8000` | 监听端口 |
| `TOP_N` | `20` | 默认返回条数（接口可在 1–20 间用 `top_n` 覆盖） |
| `MAX_CANDIDATES_PER_POSITION` | `100` | 单个位置允许提交的 OCR 候选数上限 |
| `CATEGORY_IDS` | `UJZ` | 第 4 位允许的设备类别标识：U 集装箱 / Z 挂车底盘 / J 可拆卸设备 |
| `ENABLE_CATEGORY_CORRECTION` | `true` | 是否对越类 OCR 字符做形近纠正（见下） |
| `CONFUSION_PENALTY_SCALE` | `1.0` | 形近纠正附加惩罚系数：纠正候选代价 = `-ln(conf) × (1 + scale)` |

## 请求与响应

请求体：11 个位置按位排列（位置 0–3 字母位，4–10 数字位），每位置给出候选字符与置信度（`(0, 1]`）。

```bash
curl -s -X POST http://localhost:8000/api/v1/adjudicate \
  -H 'Content-Type: application/json' \
  -d '{
    "positions": [
      {"candidates": [{"char": "M", "confidence": 0.95}, {"char": "N", "confidence": 0.4}]},
      {"candidates": [{"char": "S", "confidence": 0.92}]},
      {"candidates": [{"char": "C", "confidence": 0.90}]},
      {"candidates": [{"char": "U", "confidence": 0.97}, {"char": "V", "confidence": 0.30}]},
      {"candidates": [{"char": "1", "confidence": 0.93}]},
      {"candidates": [{"char": "2", "confidence": 0.88}]},
      {"candidates": [{"char": "3", "confidence": 0.91}]},
      {"candidates": [{"char": "A", "confidence": 0.85}]},
      {"candidates": [{"char": "5", "confidence": 0.90}]},
      {"candidates": [{"char": "6", "confidence": 0.94}]},
      {"candidates": [{"char": "6", "confidence": 0.80}, {"char": "0", "confidence": 0.50}]}
    ]
  }'
```

响应（示例精简）：

```json
{
  "request_id": "89426206207f4b5fb78175c6dfe99ed6",
  "status": "unique",
  "valid_count": 1,
  "admissible_count": 2,
  "top_n": 20,
  "results": [
    {
      "code": "MSCU1234566",
      "score": 1.280627,
      "positions": [
        {"position": 0, "char": "M", "raw_char": "M", "confidence": 0.95,
         "corrected": false, "negative_log_likelihood": 0.051293}
      ]
    }
  ]
}
```

上例中位置 7 的 OCR 输出 `A` 出现在数字位，按形近表纠正为 `4`（`corrected: true`，代价带惩罚），最终恢复合法箱号 `MSCU1234566`。

记录查询：

```bash
curl -s "http://localhost:8000/api/v1/records?limit=20&offset=0&status=unique"
curl -s "http://localhost:8000/api/v1/records/89426206207f4b5fb78175c6dfe99ed6"
```

## ISO 6346 规则要点

- 箱号 = 3 位所有人代码（A–Z）+ 1 位设备类别标识（默认允许 U/J/Z）+ 6 位注册序号（0–9）+ 1 位校验位（0–9）。
- 字母数值 A=10…Z=38，跳过 11 的倍数（11、22、33）；数字数值即其本身。
- 前 10 位字符数值乘以权重 `2^i`（i = 0…9，从左到右）求和后模 11，结果即校验位；**余数为 10 时不存在一位合法校验位，判为无效**（ISO 标准下该码作废）。
- OCR 越类字符形近纠正（可关闭）：数字位的字母如 `O/Q/D→0、I/L→1、Z→2、E→3、A→4、S→5、G→6、T→7、B→8、P→9`；字母位的数字如 `0→O、1→I、2→Z…9→P`。大小写不敏感；同一位置重复字符保留最高置信度；无法归一化的候选直接丢弃。

## 搜索算法：为什么既快又不会算错总数

直接枚举是 11 个位置候选的**无界笛卡尔积**（百万至百亿级）。本服务从不实例化完整笛卡尔积：

1. 逐位置做字符类别归一化与所有人/类别标识过滤；
2. 对前 10 位做按层 DP，状态键为「加权累计和 **mod 11**」（仅 11 个余数状态）；
3. 每个余数状态只**保留累计代价最小的前 20 条前缀**（beam），但同时维护该余数下前缀的**精确计数**；
4. 末层用校验位直接定向匹配：余数 `r`（0–9）只接数字 `r`，余数 10 无解；`valid_count` 由精确计数累加，**截断只影响返回列表，绝不影响总数**；
5. 入选完整箱号按 `(总代价, 箱号字典序)` 排序取前 20，同分决胜稳定可复现。

规模参考：6 个序号位各 10 个候选（100 万前缀 / 千万级完整笛卡尔积空间）在普通环境下约 20ms 完成，报告的 `valid_count=909091` 与独立穷举完全一致。

**beam 截断为什么不影响 top 20 正确性**：同一余数状态的任意前缀在后续各层面对完全相同的延伸集与附加代价，因此最终排名第 21 及更后的前缀不可能反超同状态保留的前 20 条前缀。

## 本地开发与测试（不使用 Docker）

```bash
pip install -r requirements.txt
pip install pytest httpx
pytest -q                       # 含 60 组随机“DP vs itertools 穷举”交叉验证
DB_PATH=./dev.db python -m app.init_db
DB_PATH=./dev.db uvicorn app.main:app --reload --port 8000
```

## 项目结构

```
.
├── app/
│   ├── main.py            # FastAPI 路由：裁决 / 记录查询 / 健康检查
│   ├── adjudication.py    # 归一化 + 余数 DP 联合裁决引擎（纯标准库）
│   ├── iso6346.py         # ISO 6346 字母数值与模 11 校验位
│   ├── database.py        # SQLite 建库 / 写入 / 查询
│   ├── schemas.py         # Pydantic v2 请求响应模型
│   ├── config.py          # 环境变量配置
│   └── init_db.py         # 容器启动建库入口
├── tests/                 # pytest：算法对拍 + API 端到端
├── docker/entrypoint.sh   # 启动时幂等装依赖、建库、起服务
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```
