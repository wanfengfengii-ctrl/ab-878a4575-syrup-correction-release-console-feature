"""稳健刻度方案测试：以小范围穷举为判据，验证断点择优与穷举定义的全局最优一致。

穷举按业务定义逐刻度 n=1..n_max 计算两端点终态糖度与最坏偏差，
g 同值取较小 n；服务端的断点算法必须与其结果逐项一致
（最优 n、最坏偏差、终态糖度区间、可行性、容差缺口）。

另覆盖：同值取小刻度、无可行解、容量放不下一个刻度、
超大范围（n_max 达 10^28 以上）仍不逐刻度线性遍历，以及输入校验与原契约兼容。
"""

import random
import time
from decimal import Decimal, localcontext
from fractions import Fraction

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.service import COMPUTE_PRECISION

client = TestClient(app)

SCALE = 10000


def post(payload):
    return client.post("/api/robust-plan", json=payload)


def fields_of(body):
    return [e["field"] for e in body["errors"]]


# ---------- 穷举判据（业务定义的直接翻译，仅用于小范围） ----------


def _scaled_int(value) -> int:
    return int(Decimal(value).scaleb(4))


def exhaustive(payload):
    """逐刻度穷举 1..n_max（Fraction 精确），返回与服务对照的期望值。

    返回 None 表示容量放不下一个刻度。
    """
    V, C, T, S, K, Q, U, E = (_scaled_int(payload[name]) for name in (
        "V", "C", "T", "S", "K", "Q", "U", "E"))
    n_max = (K - V) // Q
    if n_max < 1:
        return None
    best = None
    for n in range(1, n_max + 1):
        denom = V + n * Q
        f_low = Fraction(V * C + n * Q * (S - U), denom) / SCALE
        f_high = Fraction(V * C + n * Q * (S + U), denom) / SCALE
        target = Fraction(T) / SCALE
        worst = max(target - f_low, f_high - target)
        # 穷举定义：最坏偏差最小；同值取较小 n（升序且严格小于才更新）
        if best is None or worst < best[1]:
            best = (n, worst, f_low, f_high)
    n, worst, f_low, f_high = best
    tolerance = Fraction(E) / SCALE

    def to_dec(fr: Fraction) -> Decimal:
        with localcontext() as ctx:
            ctx.prec = COMPUTE_PRECISION
            return Decimal(fr.numerator) / Decimal(fr.denominator)

    return {
        "n": n,
        "feasible": worst <= tolerance,
        "worst": to_dec(worst),
        "finalSugarLow": to_dec(f_low),
        "finalSugarHigh": to_dec(f_high),
        "gap": None if worst <= tolerance else to_dec(worst - tolerance),
    }


def quant4(x: Decimal) -> Decimal:
    return x.quantize(Decimal("0.0001"))


def random_case(rng):
    """生成 n_max 很小（1..12）的合法输入，保证穷举成本可控。"""
    c = quant4(Decimal(rng.randint(1, 3000)) / 100)
    t = quant4(c + Decimal(rng.randint(1, 2000)) / 100)
    s = quant4(t + Decimal(rng.randint(1, max(1, int(10000 - float(t) * 100)))) / 100)
    v = quant4(Decimal(rng.randint(100, 200000)) / 100)
    q = quant4(Decimal(rng.randint(1, 5000)) / 100)
    n_want = rng.randint(1, 12)
    k = quant4(v + q * Decimal(n_want) + Decimal(rng.randint(0, max(0, int(q * 10000) - 1))) / 10000)
    # U 必须同时满足 S-U>T 与 S+U<=100
    u_max = min(s - t - Decimal("0.0001"), Decimal(100) - s)
    u = quant4(Decimal(rng.randint(0, max(0, int(u_max * 10000))) / 10000) if u_max > 0 else Decimal(0))
    e = quant4(Decimal(rng.randint(0, 3000)) / 10000)
    return {"V": v, "C": c, "T": t, "S": s, "K": k, "Q": q, "U": u, "E": e}


def assert_matches_exhaustive(payload, expected):
    resp = post({k: str(v) for k, v in payload.items()})
    assert resp.status_code == 200, (payload, resp.text)
    body = resp.json()
    assert body["n"] == expected["n"], payload
    assert Decimal(body["worstDeviation"]) == expected["worst"], payload
    assert Decimal(body["finalSugarLow"]) == expected["finalSugarLow"], payload
    assert Decimal(body["finalSugarHigh"]) == expected["finalSugarHigh"], payload
    assert Decimal(body["dose"]) == expected["n"] * Decimal(payload["Q"])
    assert Decimal(body["finalVolume"]) == Decimal(payload["V"]) + expected["n"] * Decimal(payload["Q"])
    assert body["feasible"] == expected["feasible"], payload
    if expected["feasible"]:
        assert body["status"] == "ROBUST"
        assert body["message"] == "稳健刻度"
        assert body["minToleranceGap"] is None
    else:
        assert body["status"] == "NO_ROBUST"
        assert Decimal(body["minToleranceGap"]) == expected["gap"]


# ---------- 小范围穷举判据：断点算法必须与全局最优一致 ----------


@pytest.mark.parametrize("seed", range(40))
def test_breakpoint_optimum_matches_exhaustive(seed):
    rng = random.Random(1000 + seed)
    for _ in range(50):
        payload = random_case(rng)
        expected = exhaustive(payload)
        assert expected is not None  # 生成器保证至少放得下一个刻度
        assert_matches_exhaustive(payload, expected)


def test_optimum_may_choose_lower_or_upper_breakpoint_neighbor():
    # 同一组输入下不同 U/E 都会走到；此处固定一组手算可核验的断点邻域案例
    payload = {
        "V": "500", "C": "5", "T": "8", "S": "30",
        "K": "560", "Q": "10", "U": "2", "E": "0.5",
    }
    expected = exhaustive(payload)
    assert_matches_exhaustive(payload, expected)


def test_tie_prefers_smaller_n():
    # 构造 g(1)==g(2) 且二者同为全局最小的精确案例：
    # V=1,Q=1,S-T=2,U=1,T-C=3（×10000 缩放单位），g(1)=g(2)=1，n>=3 更大
    payload = {
        "V": "0.0001", "C": "1", "T": "1.0003", "S": "1.0005",
        "K": "0.0015", "Q": "0.0001", "U": "0.0001", "E": "999",
    }
    expected = exhaustive(payload)
    assert expected["n"] == 1  # 穷举定义同值取较小 n
    assert_matches_exhaustive(payload, expected)


# ---------- 可行 / 不可行业务结果 ----------


def test_robust_mainline_fields():
    # 手算友好案例：V=500,C=5,T=8,S=30,K=600,Q=10,U=0
    payload = {"V": "500", "C": "5", "T": "8", "S": "30", "K": "600", "Q": "10", "U": "0", "E": "0.5"}
    resp = post(payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ROBUST"
    assert body["message"] == "稳健刻度"
    n = body["n"]
    assert Decimal(body["dose"]) == n * Decimal("10")
    assert Decimal(body["finalVolume"]) == Decimal(500) + Decimal(body["dose"])
    # U=0：区间退化为单点
    assert Decimal(body["finalSugarLow"]) == Decimal(body["finalSugarHigh"])
    assert Decimal(body["worstDeviation"]) <= Decimal("0.5")
    assert body["minToleranceGap"] is None
    assert set(body["inputs"]) == {"V", "C", "T", "S", "K", "Q", "U", "E"}


def test_no_robust_reports_gap_without_dose_suppression():
    # 容差 E=0：除恰好命中的特例外部署不可行，返回最小容差缺口（最优偏差仍展示）
    payload = {"V": "500", "C": "5", "T": "8", "S": "30", "K": "560", "Q": "10", "U": "2", "E": "0"}
    resp = post(payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["feasible"] is False
    assert body["status"] == "NO_ROBUST"
    assert Decimal(body["minToleranceGap"]) == Decimal(body["worstDeviation"])
    # 无稳健刻度时仍给出最优刻度与终态区间，供操作员对照缺口
    assert body["n"] is not None and Decimal(body["dose"]) > 0


def test_worst_deviation_within_tolerance_boundary_is_inclusive():
    # 取最优最坏偏差按四位小数向下取整为 E：完整精度下 E<worst，仍不可行
    base = {"V": "500", "C": "5", "T": "8", "S": "30", "K": "560", "Q": "10", "U": "2"}
    worst = Decimal(post({**base, "E": "0"}).json()["worstDeviation"])
    e_floor = worst.quantize(Decimal("0.0001"))
    assert post({**base, "E": str(e_floor)}).json()["status"] == "NO_ROBUST"
    assert post({**base, "E": str(e_floor + Decimal("0.0001"))}).json()["status"] == "ROBUST"


def test_no_capacity_for_even_one_tick_is_business_result():
    # V+Q > K：容量放不下一个刻度，返回业务结果而非字段错误
    payload = {"V": "500", "C": "5", "T": "8", "S": "30", "K": "505", "Q": "10", "U": "1", "E": "0.1"}
    resp = post(payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["feasible"] is False
    assert body["status"] == "NO_CAPACITY"
    assert body["n"] is None
    assert body["dose"] is None
    assert body["finalVolume"] is None
    assert body["finalSugarLow"] is None
    assert body["finalSugarHigh"] is None
    assert body["worstDeviation"] is None
    assert body["minToleranceGap"] is None


def test_exactly_one_tick_fits():
    # V+Q == K：恰好放得下一个刻度（等号允许）
    payload = {"V": "500", "C": "5", "T": "8", "S": "30", "K": "510", "Q": "10", "U": "1", "E": "99"}
    body = post(payload).json()
    assert body["n"] == 1
    assert Decimal(body["finalVolume"]) == Decimal(510)


def test_endpoint_sugars_need_not_straddle_target():
    # 剂量过小时两端点终态都可能低于 T：终态区间必须是两个真实端点值，而非 T±最坏偏差
    payload = {
        "V": "1036", "C": "13.27", "T": "32.69", "S": "45.05",
        "K": "1047.4319", "Q": "3.96", "U": "2.4675", "E": "0.1497",
    }
    expected = exhaustive(payload)
    body = post(payload).json()
    assert Decimal(body["finalSugarHigh"]) < Decimal("32.69")
    assert_matches_exhaustive(payload, expected)


# ---------- 超大范围不线性遍历 ----------


def test_huge_range_does_not_scan_and_stays_optimal():
    # n_max 约 10^38：断点法只评估至多 8 个候选，必须毫秒级返回且结果全局最优
    payload = {
        "V": "1", "C": "0.0001", "T": "0.0002", "S": "0.0004",
        "K": "99999999999999999999999999999.9999",
        "Q": "0.0001", "U": "0.0001", "E": "0.5",
    }
    started = time.perf_counter()
    resp = post(payload)
    elapsed = time.perf_counter() - started
    assert resp.status_code == 200
    assert elapsed < 2.0

    # 独立按断点定义（非逐刻度）复核最优：三个实数断点的相邻整数 + 容量边界
    V, C, T, S, K, Q, U, E = (_scaled_int(x) for x in payload.values())
    n_max = (K - V) // Q
    target = V * (T - C)
    candidates = {1, n_max}
    for slope in (Q * (S + U - T), Q * (S - U - T), Q * (S - T)):
        f = target // slope
        candidates |= {x for x in (f, f + 1) if 1 <= x <= n_max}

    def worst_of(n):
        p_low = target - n * Q * (S - U - T)
        p_high = n * Q * (S + U - T) - target
        return Fraction(max(p_low, p_high), V + n * Q)

    expected_n = min(sorted(candidates), key=lambda n: worst_of(n))
    body = resp.json()
    assert body["n"] == expected_n
    assert 1 <= body["n"] <= n_max


def test_huge_optimum_breakpoint_is_astronomically_large():
    # 最优点本身在 ~5×10^29 处：只有断点相邻整数能命中，逐刻度扫描不可行
    v, c, t, s, q, u = 10**24, 10000, 510000, 510001, 1, 0
    n_star = Fraction(v * (t - c), q * (s - t))
    n_floor = int(n_star)
    k = v + (n_floor + 5) * q
    payload = {
        "V": str(Decimal(v) / SCALE), "C": "1", "T": "51", "S": "51.0001",
        "K": str(Decimal(k) / SCALE), "Q": "0.0001", "U": "0", "E": "0.0001",
    }
    started = time.perf_counter()
    body = post(payload).json()
    assert time.perf_counter() - started < 2.0
    assert body["n"] in (n_floor, n_floor + 1)


# ---------- 输入校验：按 Q、U、E 顺序返回全部字段错误 ----------


def test_q_u_e_errors_collected_in_order():
    payload = {"V": "500", "C": "5", "T": "8", "S": "30", "K": "600", "Q": "0", "U": "-1", "E": "-1"}
    resp = post(payload)
    assert resp.status_code == 422
    assert fields_of(resp.json()) == ["Q", "U", "E"]


def test_q_must_be_positive():
    resp = post({"V": "500", "C": "5", "T": "8", "S": "30", "K": "600", "Q": "-2", "U": "0", "E": "0"})
    assert "Q" in fields_of(resp.json())


def test_u_lower_bound_must_be_above_target():
    # S-U == T：等号即非法（必须严格大于）
    resp = post({"V": "500", "C": "5", "T": "8", "S": "10", "K": "600", "Q": "10", "U": "2", "E": "0"})
    assert "U" in fields_of(resp.json())


def test_u_upper_bound_must_not_exceed_100():
    resp = post({"V": "500", "C": "5", "T": "8", "S": "99.9999", "K": "600", "Q": "10", "U": "0.0002", "E": "0"})
    assert "U" in fields_of(resp.json())


def test_u_bounds_boundary_values_accepted():
    # S+U == 100 允许
    assert post({"V": "500", "C": "5", "T": "8", "S": "98", "K": "600", "Q": "10", "U": "2", "E": "99"}).status_code == 200
    # U == 0 允许
    assert post({"V": "500", "C": "5", "T": "8", "S": "30", "K": "600", "Q": "10", "U": "0", "E": "99"}).status_code == 200


def test_decimal_precision_and_format_validation():
    for bad, field in (("1.23456", "Q"), ("1.23456", "U"), ("1.23456", "E"), ("abc", "E"), ("NaN", "Q")):
        resp = post({"V": "500", "C": "5", "T": "8", "S": "30", "K": "600",
                     "Q": bad if field == "Q" else "10",
                     "U": bad if field == "U" else "0",
                     "E": bad if field == "E" else "0"})
        assert resp.status_code == 422
        assert field in fields_of(resp.json()), (bad, field)


def test_missing_q_is_located():
    resp = post({"V": "500", "C": "5", "T": "8", "S": "30", "K": "600", "U": "0", "E": "0"})
    assert resp.status_code == 422
    errors = resp.json()["errors"]
    assert any(e["field"] == "Q" and "必填" in e["message"] for e in errors)
    assert "n" not in resp.json()


def test_extra_field_rejected():
    resp = post({"V": "500", "C": "5", "T": "8", "S": "30", "K": "600", "Q": "10", "U": "0", "E": "0", "X": 1})
    assert resp.status_code == 422


def test_base_five_relations_still_validated():
    # 复用 /api/judge 五项：T<=C 等关系错误照常整单拒绝
    resp = post({"V": "500", "C": "5", "T": "3", "S": "30", "K": "600", "Q": "10", "U": "0", "E": "0"})
    assert resp.status_code == 422
    assert "T" in fields_of(resp.json())


def test_forbidden_judgment_inputs_rejected_by_relations_only():
    # 稳健方案要求五项本身合法即可；V+x>K（判定禁止）并不影响本接口字段校验
    resp = post({"V": "500", "C": "5", "T": "8", "S": "30", "K": "505", "Q": "10", "U": "1", "E": "0.1"})
    assert resp.status_code == 200  # 容量放不下一个刻度是业务结果


# ---------- 既有契约兼容 ----------


def test_judge_contract_unchanged():
    resp = client.post(
        "/api/judge",
        json={"V": "500", "C": "5", "T": "8", "S": "30", "K": "600"},
    )
    assert resp.status_code == 200
    assert set(resp.json()) == {
        "verdict", "message", "dose", "finalVolume", "remainingCapacity", "excess", "inputs",
    }


def test_drain_plan_contract_unchanged():
    resp = client.post(
        "/api/drain-plan",
        json={"V": "500", "C": "5", "T": "8", "S": "30", "K": "550", "D": "20"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "EXECUTABLE"
