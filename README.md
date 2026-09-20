# ISO 6346 集装箱箱号模糊识别裁决 API

接收 11 位 ISO 6346 箱号各位置的 OCR 候选字符及置信度，联合
**字符类别规则 + 箱主代码规则 + 模 11 校验位规则**进行搜索裁决，返回有效候选
总数与排序后的前 20 项，并将每次裁决持久化到 SQLite 可供查询。

- 技术栈：Python 3.11 · FastAPI · SQLite（标准库 `sqlite3`，WAL 模式）
- 交互式文档：Swagger UI（`/docs`）、OpenAPI（`/openapi.json`）

## 一条命令启动

```bash
docker compose up --build
```

服务地址与端口：**http://localhost:8000**（健康检查 http://localhost:8000/health）

容器启动时由 `docker-entrypoint.sh` 完成两件事：

1. `pip install -r requirements.txt`（镜像构建时已预装，启动时再确保一次）；
2. `python -m app.init_db` —— 建表（`adjudications`、`owner_codes`）并幂等播种
   常见 BIC 箱主代码，数据落在 `/data` 命名卷中。

停止：`docker compose down`（加 `-v` 同时删除数据卷）。

## 配置（环境变量，均可缺省）

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `DB_PATH` | `/data/adjudication.db` | SQLite 数据库文件路径 |
| `ENFORCE_OWNER_REGISTRY` | `false` | 是否强制前 3 位必须是已注册箱主代码 |
| `CATEGORY_LETTERS` | `UJZ` | 第 4 位允许的类别标识符（ISO 6346） |
| `TOP_K` | `20` | 返回的排序候选条数（总数不受其影响） |
| `HOST` | `0.0.0.0` | 监听地址 |
| `PORT` | `8000` | 监听端口 |

单次请求可用请求体中的 `enforce_owner_registry` 覆盖服务端默认值。

## ISO 6346 规则

| 位置 | 1–3 | 4 | 5–10 | 11 |
| --- | --- | --- | --- | --- |
| 内容 | 箱主代码（大写字母） | 类别标识符 U/J/Z | 流水号（数字） | 校验位（数字 0–9） |

- 字母取值 A=10 … Z=38，顺序跳过 11 的倍数（11、22、33）；数字取自身值。
- 校验位 = 前 10 位 `Σ 值 × 2^(位置-1)` 对 11 取模；余数为 10 时不存在合法的
  一位校验位，该前 10 位组合直接排除。

## 请求 / 响应

`POST /api/v1/adjudicate`，`positions` 是**长度恰好为 11 的数组**，每个元素是该
位置的候选列表（字符自动转大写；同一字符重复出现时取最大置信度；置信度范围
`(0, 1]`；与位置类别不符的候选被丢弃并计入 `dropped`）：

```bash
curl -s http://localhost:8000/api/v1/adjudicate \
  -H 'Content-Type: application/json' \
  -d '{
        "positions": [
          [{"char":"C","confidence":0.97},{"char":"G","confidence":0.55}],
          [{"char":"S","confidence":0.96}],
          [{"char":"Q","confidence":0.98}],
          [{"char":"U","confidence":0.99},{"char":"J","confidence":0.4}],
          [{"char":"3","confidence":0.95}],
          [{"char":"0","confidence":0.97}],
          [{"char":"5","confidence":0.93}],
          [{"char":"4","confidence":0.96}],
          [{"char":"3","confidence":0.94}],
          [{"char":"8","confidence":0.98}],
          [{"char":"3","confidence":0.92}]
        ]
      }'
```

响应：

```json
{
  "id": "753a82290588…",
  "status": "unique",
  "total_candidates": 1,
  "top": [
    {
      "code": "CSQU3054383",
      "score": 0.4621392,
      "probability": 0.6299,
      "per_position_confidence": [0.97, 0.96, 0.98, 0.99, 0.95, 0.97, 0.93, 0.96, 0.94, 0.98, 0.92]
    }
  ],
  "dropped": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
  "empty_positions": [],
  "owner_registry_enforced": false
}
```

- `status`：
  - `unique` —— 有效候选恰好 1 个；
  - `ambiguous` —— 有效候选多于 1 个（看 `total_candidates` 与 `top`）；
  - `invalid` —— 没有任何候选同时满足全部约束（含某位置无类别合法候选、校验位
    为 10、第 11 位 OCR 未给出所需校验数字、强制箱主注册表但未注册等）。
- `total_candidates`：通过全部约束的**有效候选总数**（精确值，与是否截断无关）。
- `top`：按 `score`（各位置 `-log(置信度)` 之和，越小越优）升序的至多前
  `TOP_K`（默认 20）项；`score` 完全相等时按完整箱号字典序升序稳定决胜。
  `probability = exp(-score)` 为候选的联合置信度。
- `dropped[p]`：第 `p` 个位置因字符类别不符（如字母位出现数字）被丢弃的候选数。
- `empty_positions`：无任何类别合法候选的位置（1 基）。

## 搜索算法（不展开无界笛卡尔积）

- **总数**：前 10 位做 11 状态（模 11 余数）动态规划精确计数；第 11 位只接受唯一
  满足 `余数 = 校验位` 的 OCR 候选，余数 10 无解。计数与取前 20 完全解耦，截断
  列表不影响总数（大候选宽度下也能处理数十亿有效组合，见引擎压测）。
- **排序 Top-K**：逆向 DP 预计算每个层边界 × 每个余数下的最优后缀（最小代价，
  平局取字典序最小），再用最小堆做最佳优先分支限界；堆键为“经过该节点的最优完整
  解”`(总负对数置信度, 完整箱号)`，叶子出堆顺序即全局排名。代价用 `math.fsum`
  规范化，保证同一完整解在任意节点算出的总分位级一致。仅展开产出前 K 个答案所需
  的节点，绝不物化候选笛卡尔积。
- **箱主规则**：未强制时前 3 位只要求大写字母；强制时将三位 OCR 候选集的有界乘积
  与 `owner_codes` 注册表取交集（不对全字母表做通配展开）。

## 其他接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/health` | 健康检查 |
| GET | `/api/v1/adjudications/{id}` | 按 ID 查询单条裁决记录（含原始请求） |
| GET | `/api/v1/adjudications?limit=&offset=&status=` | 分页查询，可按 `unique`/`ambiguous`/`invalid` 过滤 |
| GET | `/api/v1/owner-codes` | 列出已注册箱主代码（3 字母） |
| POST | `/api/v1/owner-codes` | 新增/更新箱主代码，体为 `{"code":"CSQ","description":"COSCO"}` |

查询示例：

```bash
curl -s http://localhost:8000/api/v1/adjudications?status=ambiguous&limit=20
curl -s http://localhost:8000/api/v1/adjudications/753a82290588
```

## 本地开发（不使用 Docker）

```bash
python3 -m pip install -r requirements.txt
python3 -m app.init_db                 # 建库 + 播种（DB_PATH 可覆盖）
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
python3 test_engine.py                 # 引擎穷举对照测试（仅标准库）
```

## 项目结构

```
app/
  config.py       # 环境变量配置
  iso6346.py      # ISO 6346 引擎：校验位、计数 DP、最佳优先 Top-K 搜索
  db.py           # SQLite 建表、播种、裁决记录与箱主注册表读写
  schemas.py      # Pydantic 请求/响应模型与入参校验
  main.py         # FastAPI 路由
  init_db.py      # 容器启动建库入口
Dockerfile
docker-compose.yml
docker-entrypoint.sh
test_engine.py    # 引擎测试：400 组随机穷举对照 + 平局/截断/压测
requirements.txt
```
