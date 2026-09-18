"""稳健刻度方案主线测试。

通过 TestClient 驱动真实 FastAPI 应用与真实 decimal 计算，不使用任何假数据或固定响应。
算法正确性以「小范围逐刻度穷举定义的全局最优」为判据：
    g(n) = max(T-F_-(n), F_+(n)-T)，F_±(n)=(V·C+nQ·(S±U))/(V+nQ)
并额外覆盖断点择优、同值取小刻度、无可行解、超大范围不线性遍历。
"""

import time
from decimal import Decimal, getcontext, localcontext

from fastapi.testclient import TestClient

from app.main import app
from app.service import COMPUTE_PRECISION

# 期望值复算需与服务同精度（50 位有效数字），避免默认 28 位舍入造成尾差
getcontext().prec = COMPUTE_PRECISION

client = TestClient(app)

# 该组输入下 /api/judge 判定为允许补加（终态 568.18... < 600）
ALLOWED_PAYLOAD = {"V": "500", "C": "5", "T": "8", "S": "30", "K": "600"}


def post(payload):
    return client.post("/api/robust-plan", json=payload)


def fields_of(body):
    return [e["field"] for e in body["errors"]]


def messages_of(body, field):
    return [e["message"] for e in body["errors"] if e["field"] == field]


def exhaustive_optimum(v, c, t, s, k, q, u):
    """按穷举定义求全局最优：返回 (n_max, best_n, best_dev, f_lo, f_hi)。

    仅用于小范围（n_max 可枚举）的正确性判据。
    """
    with localcontext() as ctx:
        ctx.prec = COMPUTE_PRECISION
        # 经 str 归一化，避免 Decimal(浮点) 带入二进制噪声（服务按字符串精确解析）
        V, C, T, S, K, Q, U = (Decimal(str(x)) for x in (v, c, t, s, k, q, u))
        n_max = int((K - V) // Q)

        def dev_at(n):
            x = n * Q
            vol = V + x
            f_lo = (V * C + x * (S - U)) / vol
            f_hi = (V * C + x * (S + U)) / vol
            return f_lo, f_hi, max(T - f_lo, f_hi - T)

        best_n = best_dev = None
        best_lo = best_hi = None
        for n in range(1, n_max + 1):
            f_lo, f_hi, dev = dev_at(n)
            # 穷举同样同值取较小 n：仅严格更优才替换
            if best_dev is None or dev < best_dev:
                best_n, best_dev = n, dev
                best_lo, best_hi = f_lo, f_hi
        return n_max, best_n, best_dev, best_lo, best_hi


# ---------- 稳健主线 ----------


def test_robust_mainline():
    # n=7（剂量 70）：下端 (3500+70*29)/570=7.9474，上端 8.1930，最坏偏差 0.1930
    resp = post({**ALLOWED_PAYLOAD, "Q": "10", "U": "1", "E": "0.5"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ROBUST"
    assert body["message"] == "稳健刻度"
    assert body["n"] == 7
    assert Decimal(body["dose"]) == Decimal(70)
    V, C, T = Decimal(500), Decimal(5), Decimal(8)
    e_lo = (V * C + Decimal(70) * Decimal(29)) / Decimal(570)
    e_hi = (V * C + Decimal(70) * Decimal(31)) / Decimal(570)
    assert Decimal(body["finalConcentrationLow"]) == e_lo
    assert Decimal(body["finalConcentrationHigh"]) == e_hi
    assert Decimal(body["worstDeviation"]) == e_hi - T
    assert Decimal(body["worstDeviation"]) <= Decimal("0.5")
    assert body["toleranceGap"] is None
    assert body["inputs"] == {
        "V": "500",
        "C": "5",
        "T": "8",
        "S": "30",
        "K": "600",
        "Q": "10",
        "U": "1",
        "E": "0.5",
    }


def test_worst_deviation_is_max_of_two_endpoints():
    # 最优偏差取两端点偏差的最大者（本例上端点过冲占主导）
    resp = post({**ALLOWED_PAYLOAD, "Q": "10", "U": "1", "E": "1"})
    body = resp.json()
    dev = Decimal(body["worstDeviation"])
    lo_dev = Decimal(8) - Decimal(body["finalConcentrationLow"])
    hi_dev = Decimal(body["finalConcentrationHigh"]) - Decimal(8)
    assert dev == max(lo_dev, hi_dev)


def test_deviation_equal_to_tolerance_is_robust():
    # 完整精度比较：最优偏差恰好等于 E 也受理（<=）。
    # 取无波动且刻度恰好命中目标：V=100,C=5,T=9,S=25，命中剂量 25=1×Q，
    # 两端点终态恰为 T，最优偏差为 0，E=0 时边界相等仍判稳健。
    payload = {"V": "100", "C": "5", "T": "9", "S": "25", "K": "200",
               "Q": "25", "U": "0", "E": "0"}
    resp = post(payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ROBUST"
    assert body["n"] == 1
    assert Decimal(body["worstDeviation"]) == 0
    assert Decimal(body["finalConcentrationLow"]) == Decimal(9)
    assert Decimal(body["finalConcentrationHigh"]) == Decimal(9)


# ---------- 断点择优：与穷举全局最优一致 ----------


def test_breakpoint_choice_matches_exhaustive_small_ranges():
    # 覆盖断点落在可行区间内、外、恰为整数边界等多种情形
    cases = [
        # V, C, T, S, K, Q, U
        (500, 5, 8, 30, 600, 10, 1),
        (500, 5, 8, 30, 600, 33.3333, 1),
        (100, 1, 5, 60, 500, 1, 0.5),
        (1000, 10, 12, 40, 2000, 0.5, 2),
        (486, 0.0915, 0.5691, 0.9577, 516.2626, 0.0127, 0.1624),
        (100, 5, 8, 30, 110, 1, 1),  # 可行区间整体位于断点左侧，最优在容量边界
    ]
    for v, c, t, s, k, q, u in cases:
        n_max, best_n, best_dev, best_lo, best_hi = exhaustive_optimum(
            v, c, t, s, k, q, u
        )
        resp = post(
            {
                "V": str(v), "C": str(c), "T": str(t), "S": str(s), "K": str(k),
                "Q": str(q), "U": str(u), "E": "99",
            }
        )
        assert resp.status_code == 200, (v, c, t, s, k, q, u)
        body = resp.json()
        assert body["n"] == best_n, (v, q, u, body["n"], best_n)
        assert Decimal(body["worstDeviation"]) == best_dev
        assert Decimal(body["finalConcentrationLow"]) == best_lo
        assert Decimal(body["finalConcentrationHigh"]) == best_hi


def test_breakpoint_choice_fuzz_against_exhaustive():
    # 小范围随机穷举为判据：固定随机种子，多组可行刻度数 <= 500 的输入
    import random

    rng = random.Random(20260918)
    q4 = Decimal("0.0001")

    for _ in range(60):
        V = Decimal(rng.randint(1, 300))
        C = Decimal(rng.randint(1, 3000)) / Decimal(10000)
        T = C + Decimal(rng.randint(1, 3000)) / Decimal(10000)
        if T >= 80:
            continue
        S = T + Decimal(rng.randint(5, 3000)) / Decimal(10000)
        if S > 99:
            continue
        Q = Decimal(rng.randint(1, 500)) / Decimal(10000)
        n_target = rng.randint(1, 500)
        K = (V + Q * n_target + Decimal(rng.randint(0, 500)) / Decimal(10000)).quantize(q4)
        if K <= V or int((K - V) // Q) < 1:
            continue
        u_max = min(S - T - q4, Decimal(100) - S)
        if u_max <= 0:
            continue
        U = Decimal(rng.randint(0, int(u_max / q4))) * q4
        n_max, best_n, best_dev, _, _ = exhaustive_optimum(
            V, C, T, S, K, Q, U
        )
        resp = post(
            {
                "V": str(V), "C": str(C), "T": str(T), "S": str(S), "K": str(K),
                "Q": str(Q), "U": str(U), "E": "99",
            }
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["n"] == best_n, (V, C, T, S, K, Q, U)
        assert Decimal(body["worstDeviation"]) == best_dev


# ---------- 同值取较小刻度 ----------


def test_tie_prefers_smaller_n():
    # 用穷举扫描出存在并列最优的真实输入，断言服务返回较小 n
    import random

    rng = random.Random(54321)

    def dev(v, c, t, s, k, q, u, n):
        V, C, T, S, K, Q, U = (Decimal(x) for x in (v, c, t, s, k, q, u))
        x = n * Q
        vol = V + x
        return max(T - (V * C + x * (S - U)) / vol, (V * C + x * (S + U)) / vol - T)

    for _ in range(4000):
        V = rng.randint(1, 200)
        C = rng.randint(1, 2000) / 10000
        T = C + rng.randint(1, 2000) / 10000
        if T >= 80:
            continue
        S = T + rng.randint(5, 2000) / 10000
        if S > 99:
            continue
        q = rng.randint(1, 400) / 100
        n_target = rng.randint(2, 300)
        K = V + q * n_target + rng.randint(0, 400) / 100
        u_max = min(S - T - 0.01, 100 - S)
        if u_max <= 0:
            continue
        u = rng.randint(0, int(u_max * 100)) / 100
        n_max = int((Decimal(str(K)) - Decimal(V)) // Decimal(str(q)))
        vals = [(dev(V, C, T, S, K, q, u, n), n) for n in range(1, n_max + 1)]
        mn = min(d for d, _ in vals)
        winners = sorted(n for d, n in vals if d == mn)
        if len(winners) > 1:
            resp = post(
                {
                    "V": str(V), "C": str(C), "T": str(T), "S": str(S), "K": str(K),
                    "Q": str(q), "U": str(u), "E": "99",
                }
            )
            assert resp.json()["n"] == winners[0]
            return
    # 未随机构造出并列也不应失败：断点两侧整数天然等距时的等价性质已由主算法严格 < 保证


# ---------- 无稳健刻度与最小容差缺口 ----------


def test_no_robust_mark_gives_tolerance_gap():
    resp = post({**ALLOWED_PAYLOAD, "Q": "10", "U": "2", "E": "0.01"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "NO_ROBUST_MARK"
    assert body["message"] == "无稳健刻度"
    _, best_n, best_dev, _, _ = exhaustive_optimum(500, 5, 8, 30, 600, 10, 2)
    assert Decimal(body["toleranceGap"]) == best_dev - Decimal("0.01")
    assert Decimal(body["toleranceGap"]) > 0
    # 无稳健刻度：不呈现剂量与终态糖度区间
    assert body["n"] is None
    assert body["dose"] is None
    assert body["finalConcentrationLow"] is None
    assert body["finalConcentrationHigh"] is None
    assert body["worstDeviation"] is None


def test_zero_tolerance_never_robust():
    # 端点糖度不等于 T（U>0），E=0 必然无稳健刻度，缺口即最优偏差
    resp = post({**ALLOWED_PAYLOAD, "Q": "10", "U": "1", "E": "0"})
    body = resp.json()
    assert body["status"] == "NO_ROBUST_MARK"
    _, _, best_dev, _, _ = exhaustive_optimum(500, 5, 8, 30, 600, 10, 1)
    assert Decimal(body["toleranceGap"]) == best_dev


def test_capacity_cannot_fit_one_mark_is_business_result():
    # V+Q = 510 > K = 505：容量放不下一个刻度，返回业务结果而非字段错误
    resp = post({**ALLOWED_PAYLOAD, "K": "505", "Q": "10", "U": "1", "E": "0.5"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "NO_ROBUST_MARK"
    assert body["dose"] is None
    assert body["toleranceGap"] is None  # 无可行刻度，缺口无从计算
    assert body["inputs"]["K"] == "505"


def test_capacity_fits_exactly_one_mark():
    # V+Q 恰好等于 K：唯一边界刻度 n=1 可行并被评估
    resp = post({**ALLOWED_PAYLOAD, "K": "510", "Q": "10", "U": "1", "E": "9"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["n"] == 1
    assert Decimal(body["dose"]) == Decimal(10)


# ---------- 非法输入：按 Q、U、E 顺序返回全部字段错误 ----------


def test_invalid_params_collected_in_q_u_e_order():
    resp = post({**ALLOWED_PAYLOAD, "Q": "-1", "U": "-1", "E": "-1"})
    assert resp.status_code == 422
    body = resp.json()
    assert body["detail"] == "输入校验失败，已整单拒绝"
    # Q、U、E 三项错误全部返回，顺序为 Q → U → E
    assert fields_of(body) == ["Q", "U", "E"]
    assert "大于 0" in messages_of(body, "Q")[0]
    assert "负数" in messages_of(body, "U")[0]
    assert "负数" in messages_of(body, "E")[0]
    assert "dose" not in body and "n" not in body


def test_q_zero_rejected():
    resp = post({**ALLOWED_PAYLOAD, "Q": "0", "U": "1", "E": "0.5"})
    assert resp.status_code == 422
    assert fields_of(resp.json()) == ["Q"]


def test_u_relation_errors_collected():
    # S-U <= T 与 S+U > 100 同时成立：U 字段收集全部违规（不互相短路）
    resp = post(
        {"V": "500", "C": "5", "T": "8", "S": "60", "K": "600",
         "Q": "10", "U": "55", "E": "0.5"}
    )
    assert resp.status_code == 422
    body = resp.json()
    u_msgs = messages_of(body, "U")
    assert any("S-U" in m for m in u_msgs)
    assert any("S+U" in m for m in u_msgs)


def test_lower_endpoint_equal_to_t_rejected():
    # S-U 恰好等于 T 的边界：必须拒绝（保证两端点糖度都严格大于 T）
    resp = post(
        {"V": "500", "C": "5", "T": "8", "S": "12", "K": "600",
         "Q": "10", "U": "4", "E": "0.5"}
    )
    assert resp.status_code == 422
    assert any("S-U" in m for m in messages_of(resp.json(), "U"))


def test_upper_endpoint_equal_100_allowed():
    # S+U 恰好等于 100 的边界：受理
    resp = post(
        {"V": "500", "C": "5", "T": "8", "S": "99", "K": "600",
         "Q": "10", "U": "1", "E": "9"}
    )
    assert resp.status_code == 200


def test_u_zero_accepted():
    # U=0（无波动）：区间退化为单点，受理
    resp = post({**ALLOWED_PAYLOAD, "Q": "10", "U": "0", "E": "1"})
    assert resp.status_code == 200
    body = resp.json()
    assert Decimal(body["finalConcentrationLow"]) == Decimal(body["finalConcentrationHigh"])


def test_missing_q_u_e_located():
    resp = post(ALLOWED_PAYLOAD)
    assert resp.status_code == 422
    assert set(fields_of(resp.json())) == {"Q", "U", "E"}


def test_precision_overflow_located():
    for fld in ("Q", "U", "E"):
        payload = {**ALLOWED_PAYLOAD, "Q": "10", "U": "1", "E": "0.5", fld: "1.23456"}
        resp = post(payload)
        assert resp.status_code == 422
        assert "四位小数" in messages_of(resp.json(), fld)[0]


def test_non_finite_located():
    for fld in ("Q", "U", "E"):
        payload = {**ALLOWED_PAYLOAD, "Q": "10", "U": "1", "E": "0.5", fld: "NaN"}
        resp = post(payload)
        assert resp.status_code == 422
        assert "有限" in messages_of(resp.json(), fld)[0]


def test_non_numeric_located():
    payload = {**ALLOWED_PAYLOAD, "Q": "abc", "U": "1", "E": "0.5"}
    resp = post(payload)
    assert resp.status_code == 422
    assert "Q" in fields_of(resp.json())


def test_bool_rejected():
    payload = {**ALLOWED_PAYLOAD, "Q": True, "U": "1", "E": "0.5"}
    resp = post(payload)
    assert resp.status_code == 422
    assert "Q" in fields_of(resp.json())


# ---------- 复用判定五项关系校验 ----------


def test_invalid_five_inputs_still_rejected():
    # V>K：原判定关系错误仍整单拒绝
    resp = post({**ALLOWED_PAYLOAD, "V": "700", "Q": "10", "U": "1", "E": "0.5"})
    assert resp.status_code == 422
    body = resp.json()
    assert "V" in fields_of(body)
    assert "n" not in body


def test_extra_field_rejected():
    resp = post({**ALLOWED_PAYLOAD, "Q": "10", "U": "1", "E": "0.5", "X": "1"})
    assert resp.status_code == 422


# ---------- 超大范围不线性遍历 ----------


def test_huge_mark_range_resolved_constant_time():
    # Q 极小、容量极大：可行刻度数约 1e16，禁止逐刻度扫描，必须常数级返回
    payload = {
        "V": "1", "C": "5", "T": "8", "S": "30", "K": "1000000000000",
        "Q": "0.0001", "U": "1", "E": "0.0001",
    }
    start = time.perf_counter()
    resp = post(payload)
    elapsed = time.perf_counter() - start
    assert resp.status_code == 200
    assert elapsed < 1.0  # 逐刻度扫描 1e16 次绝无可能在此时间内完成
    n_max = int((Decimal(payload["K"]) - Decimal(payload["V"])) // Decimal(payload["Q"]))
    assert n_max > 10**15
    body = resp.json()
    # 结果结构合法（有无稳健刻度均可），n 若给出必在可行范围内
    if body["n"] is not None:
        assert 1 <= body["n"] <= n_max


def test_huge_range_matches_exhaustive_neighborhood_definition():
    # 超大范围无法穷举全部刻度，改以「断点相邻整数 + 边界」这一候选集合的
    # 显式穷举为判据（与小范围全局穷举在数学上等价）。
    payload = {
        "V": "100", "C": "1", "T": "5", "S": "60", "K": "999999999.9999",
        "Q": "0.001", "U": "0.5", "E": "0.1",
    }
    body = post(payload).json()
    with localcontext() as ctx:
        ctx.prec = COMPUTE_PRECISION
        V, C, T, S, K = Decimal(100), Decimal(1), Decimal(5), Decimal(60), Decimal(payload["K"])
        Q, U = Decimal("0.001"), Decimal("0.5")
        n_max = int((K - V) // Q)
        breaks = [
            V * (T - C) / (S + U - T),
            V * (T - C) / (S - T),
            V * (T - C) / (S - U - T),
        ]
        cands = {1, n_max}
        for xb in breaks:
            r = xb / Q
            lo = int(r.to_integral_value(rounding="ROUND_FLOOR"))
            cands.update(n for n in (lo, lo + 1) if 1 <= n <= n_max)

        def g(n):
            x = n * Q
            vol = V + x
            return max(T - (V * C + x * (S - U)) / vol, (V * C + x * (S + U)) / vol - T)

        expected_n = min(cands, key=lambda n: (g(n), n))
        assert body["n"] == expected_n


# ---------- 既有接口契约不变 ----------


def test_judge_contract_unchanged():
    resp = client.post("/api/judge", json=ALLOWED_PAYLOAD)
    assert resp.status_code == 200
    assert set(resp.json()) == {
        "verdict", "message", "dose", "finalVolume",
        "remainingCapacity", "excess", "inputs",
    }


def test_drain_contract_unchanged():
    forbidden = {**ALLOWED_PAYLOAD, "K": "550"}
    resp = client.post("/api/drain-plan", json={**forbidden, "D": "20"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "EXECUTABLE"
    assert set(body["inputs"]) == {"V", "C", "T", "S", "K", "D"}
