# 单罐补加判定台

饮料车间配液罐实测糖度偏低时，计算**唯一补加剂量**并在可能溢罐时**明确阻断**的判定台。
React + TypeScript + Vite 前端与 Python 3.12 + FastAPI + Pydantic 后端真实联调。

## 判定规则

- 输入：当前体积 `V`、当前糖度 `C`、目标糖度 `T`、糖浆糖度 `S`、罐体容量 `K`
- 体积单位为毫升（mL），糖度为质量分数百分数（%），假定液体密度相同
- 仅当 `0 < C < T < S ≤ 100`、`V > 0`、`K > 0`、`V ≤ K` 且各输入**最多四位小数**时受理
- 按质量守恒以 `decimal`（50 位有效数字）计算唯一补加量：

  ```
  V·C + x·S = (V + x)·T   =>   x = V×(T-C)/(S-T)
  ```

- 以**未因展示格式改变的完整精度计算值**判定 `V + x ≤ K`：等于容量允许，超过容量禁止
- 放行时展示：公式代入、唯一补加量、终态体积、剩余容量与「允许补加」
- 容量不足时展示：超出量与「禁止补加」
- 展示数值最多保留四位小数（四舍五入）并去除无意义尾零；精确值非零但舍入后为 0
  （|值| < 0.00005）时显示 `<0.0001`，明确指示仍有微量，避免与「禁止补加」矛盾
- 空值、非有限数（NaN/∞）、精度超限或关系错误：HTTP 422 定位字段、整单拒绝，前端清除旧结论

## 腾容方案

判定为「禁止补加」时，操作员可在该结论下发起**生成腾容方案**，填写本次最多可排出的
当前料液量 `D`；系统复用原五项输入计算恢复补加所需的最小排出量，**不改写原判定**。

- 业务假设：排出的当前料液糖度仍为 `C`（罐内混合均匀）
- 以 `decimal`（50 位有效数字）反解最小排出量，使排出后补加的终态恰好顶到容量上限：

  ```
  (V-d)·C + (K-(V-d))·S = K·T   =>   d = V - K×(S-T)/(S-C)
  ```

- 排出后的糖浆剂量仍按原质量守恒公式 `x = (V-d)×(T-C)/(S-T)` 计算
- 以**完整精度**比较 `d` 与 `D`，只形成两种结果：
  - `d ≤ D` → **可执行**：展示 d、排出后体积、补加量与恰好不超过容量的终态
  - `d > D` → **超出排出上限**：展示仍缺少的排出量 `d-D`，不呈现可执行剂量
- `D` 为空、负数、精度超限或不小于 `V`：HTTP 422 定位 `D` 字段，
  前端清除旧方案但**保留原禁止结论**；请求失败也不会把腾容结果误作原始判定
- 「允许补加」结论下不出现腾容入口；若直接对允许补加的输入请求腾容
  （`d ≤ 0`，含终态恰等于容量的边界），HTTP 422 整单拒绝，不生成方案

## 稳健刻度方案

判定为「允许补加」时，若现场泵按**固定刻度**投料且糖浆糖度存在波动，操作员可在
该结论下发起**生成稳健刻度方案**，填写单刻度量 `Q`、糖度波动 `U`、终态容差 `E`；
系统复用原五项输入在固定刻度中择优，**不改写原判定**。

- 剂量以正整数刻度数 `n` 表示为 `nQ`，仅受理容量内刻度 `V+nQ ≤ K`（等号允许）
- 糖浆实际糖度落在区间 `[S-U, S+U]`，对两端点分别按质量守恒计算终态糖度：

  ```
  F_s(n) = (V·C + nQ·s)/(V + nQ)，s ∈ {S-U, S+U}
  ```

- 在容量内刻度中选择**最坏端点偏差** `max(T-F_(S-U), F_(S+U)-T)` 最小的 `n`，
  同值取较小 `n`；最优偏差 `≤ E` 为稳健，否则为无稳健刻度
- 算法**不逐刻度扫描**：`F_s` 关于剂量单调，两端点各有唯一命中 `T` 的实数剂量
  `x_s = V×(T-C)/(s-T)`，两偏差分支在 `x₀ = V×(T-C)/(S-T)` 处相交，最坏偏差在
  `x₀` 左侧递减、右侧递增。用 Decimal 从**容量上界、两端点命中 T、偏差分支相交处**
  推导实数断点，只评估断点相邻整数与边界刻度，结果与逐刻度穷举定义的全局最优一致
- 稳健时展示：刻度数与剂量 `nQ`、终态糖度区间 `[F_(S-U), F_(S+U)]`、最坏偏差
- 无稳健刻度时展示：最小容差缺口 `最优偏差-E`，不呈现剂量与终态区间；
  容量连一个刻度都放不下（`V+Q>K`）时为业务结果，缺口无从计算
- `Q≤0`、`U<0`、`S-U≤T`、`S+U>100` 或 `E<0`：HTTP 422 按 `Q`、`U`、`E` 顺序
  一次性返回全部字段错误（`U` 可同时定位多条关系错误），前端清除旧方案但保留原允许结论
- `Q`、`U`、`E` 沿用有限数与最多四位小数校验；请求失败也不会把稳健结果误作原始判定

## 目录结构

```
├── docker-compose.yml      # web / api / verify 三个服务
├── api/                    # FastAPI 后端（Python 3.12）
│   ├── app/                #   schemas.py(校验) service.py(判定) main.py(路由)
│   └── tests/              #   pytest：放行、溢罐、非法输入主线
├── web/                    # React + TS + Vite 前端
│   ├── src/lib/            #   format(展示格式化) api(请求) view(视图模型) state(状态机)
│   ├── tests/              #   Vitest：格式化、视图模型、状态机、结论面板
│   └── nginx.conf          #   静态托管 + /api 反向代理
└── verify/                 # 一次性验收服务（pytest + httpx + Playwright）
    └── tests/              #   API 网络验收 + 真实浏览器端到端
```

## 启动（Docker Compose）

```bash
docker compose up -d --build api web
# 打开 http://localhost:8080
```

宿主端口可用环境变量覆盖（默认 `WEB_PORT=8080`、`API_PORT=8000`）：

```bash
WEB_PORT=9000 API_PORT=9001 docker compose up -d --build api web
```

## 一次性验收

`verify` 服务依赖 `api`、`web` 健康检查通过后，对运行中的服务执行
API 网络验收（httpx）与真实浏览器端到端（Playwright/Chromium），跑完即退出：

```bash
docker compose up --build --exit-code-from verify verify
# 退出码即验收结果；结束后清理：
docker compose down
```

## 本地开发

```bash
# 后端（Python 3.12）
cd api
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --port 8000

# 前端（Node 20+），开发服务器把 /api 代理到 API_PORT（默认 8000）
cd web
npm ci
npm run dev        # http://localhost:5173
```

## 测试

```bash
cd api && python -m pytest tests/ -v     # 后端：75 例
cd web && npm test                       # 前端：54 例
# 端到端：先启动 api 与 web，再执行 verify 套件
cd verify && pip install -r requirements.txt
WEB_BASE_URL=http://localhost:5173 API_BASE_URL=http://localhost:8000 python -m pytest tests -v
```

全部测试均驱动真实应用与真实计算，不使用假数据或固定响应。

## API 请求示例

```bash
curl -X POST http://localhost:8000/api/judge \
  -H 'Content-Type: application/json' \
  -d '{"V":"500","C":"5","T":"8","S":"30","K":"600"}'
```

放行响应（数值为完整精度十进制字符串，展示格式化由前端负责）：

```json
{
  "verdict": "ALLOWED",
  "message": "允许补加",
  "dose": "68.181818181818181818181818181818181818181818181818",
  "finalVolume": "568.18181818181818181818181818181818181818181818182",
  "remainingCapacity": "31.81818181818181818181818181818181818181818181818",
  "excess": null,
  "inputs": {"V": "500", "C": "5", "T": "8", "S": "30", "K": "600"}
}
```

溢罐（`K` 改为 `"550"`）：`verdict` 为 `FORBIDDEN`、`message` 为「禁止补加」，
`excess` 给出超出量、`remainingCapacity` 为 `null`。

非法输入（如 `T` 不大于 `C`）：HTTP 422，整单拒绝并定位字段——

```json
{
  "detail": "输入校验失败，已整单拒绝",
  "errors": [{"field": "T", "message": "目标糖度 T 必须大于当前糖度 C"}]
}
```

## 腾容方案 API 示例

```bash
curl -X POST http://localhost:8000/api/drain-plan \
  -H 'Content-Type: application/json' \
  -d '{"V":"500","C":"5","T":"8","S":"30","K":"550","D":"20"}'
```

可执行响应（终态恰好顶到容量上限 550，数值为完整精度十进制字符串）：

```json
{
  "status": "EXECUTABLE",
  "message": "可执行",
  "minDrain": "16",
  "volumeAfterDrain": "484",
  "dose": "66",
  "finalVolume": "550",
  "shortfall": null,
  "inputs": {"V": "500", "C": "5", "T": "8", "S": "30", "K": "550", "D": "20"}
}
```

排出上限不足（`D` 改为 `"10"`）：`status` 为 `EXCEEDS_LIMIT`、`message` 为「超出排出上限」，
`shortfall` 给出仍缺少的排出量 `6`，`dose`、`volumeAfterDrain`、`finalVolume` 均为 `null`。

## 稳健刻度方案 API 示例

```bash
curl -X POST http://localhost:8000/api/robust-plan \
  -H 'Content-Type: application/json' \
  -d '{"V":"500","C":"5","T":"8","S":"30","K":"600","Q":"10","U":"1","E":"0.5"}'
```

稳健响应（最优为 7 个刻度、剂量 70；数值为完整精度十进制字符串）：

```json
{
  "status": "ROBUST",
  "message": "稳健刻度",
  "n": 7,
  "dose": "70",
  "finalConcentrationLow": "7.9473684210526315789473684210526315789473684210526",
  "finalConcentrationHigh": "8.1929824561403508771929824561403508771929824561404",
  "worstDeviation": "0.1929824561403508771929824561403508771929824561404",
  "toleranceGap": null,
  "inputs": {"V": "500", "C": "5", "T": "8", "S": "30", "K": "600", "Q": "10", "U": "1", "E": "0.5"}
}
```

无稳健刻度（`U` 改为 `"2"`、`E` 改为 `"0.01"`）：`status` 为 `NO_ROBUST_MARK`、
`message` 为「无稳健刻度」，`toleranceGap` 给出最小容差缺口 `最优偏差-E`，
`n`、`dose`、两端点终态糖度与 `worstDeviation` 均为 `null`。容量放不下一个刻度
（`V+Q>K`）时同为业务结果，`toleranceGap` 为 `null`。非法 `Q`/`U`/`E` 返回
HTTP 422，例如：

```json
{
  "detail": "输入校验失败，已整单拒绝",
  "errors": [
    {"field": "Q", "message": "单刻度量 Q 必须大于 0"},
    {"field": "U", "message": "糖度波动 U 不能为负数"},
    {"field": "E", "message": "终态容差 E 不能为负数"}
  ]
}
```
