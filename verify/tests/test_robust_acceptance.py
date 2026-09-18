"""稳健刻度方案 API 网络验收：通过真实 HTTP 打到运行中的判定服务。

以小范围穷举为判据（逐刻度 n=1..n_max，Fraction 精确），
校验断点算法返回的最优刻度与穷举定义的全局最优逐项一致；
另覆盖同值取小刻度、无可行解、容量边界、超大范围不线性遍历与输入校验，
并确认 /api/judge、/api/drain-plan 原契约不受影响。
"""

import random
import time
from decimal import Decimal, localcontext
from fractions import Fraction

import httpx
import pytest

SCALE = 10000
BASE_PAYLOAD = {"V": "500", "C": "5", "T": "8", "S": "30", "K": "600"}


def _si(value) -> int:
    return int(Decimal(value).scaleb(4))


def exhaustive(payload):
    """穷举判据：业务定义的逐刻度直接翻译（小范围，Fraction 精确）。"""
    V, C, T, S, K, Q, U, E = (_si(payload[name]) for name in (
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
        if best is None or worst < best[1]:
            best = (n, worst, f_low, f_high)
    n, worst, f_low, f_high = best
    tol = Fraction(E) / SCALE

    def d(fr):
        with localcontext() as ctx:
            ctx.prec = 50
            return Decimal(fr.numerator) / Decimal(fr.denominator)

    return {
        "n": n,
        "feasible": worst <= tol,
        "worst": d(worst),
        "low": d(f_low),
        "high": d(f_high),
        "gap": None if worst <= tol else d(worst - tol),
    }


def quant4(x):
    return x.quantize(Decimal("0.0001"))


def random_case(rng):
    c = quant4(Decimal(rng.randint(1, 3000)) / 100)
    t = quant4(c + Decimal(rng.randint(1, 2000)) / 100)
    s = quant4(t + Decimal(rng.randint(1, max(1, int(10000 - float(t) * 100)))) / 100)
    v = quant4(Decimal(rng.randint(100, 200000)) / 100)
    q = quant4(Decimal(rng.randint(1, 5000)) / 100)
    k = quant4(v + q * Decimal(rng.randint(1, 12)) + Decimal(rng.randint(0, max(0, int(q * 10000) - 1))) / 10000)
    u_max = min(s - t - Decimal("0.0001"), Decimal(100) - s)
    u = quant4(Decimal(rng.randint(0, max(0, int(u_max * 10000))) / 10000) if u_max > 0 else Decimal(0))
    e = quant4(Decimal(rng.randint(0, 3000)) / 10000)
    return {"V": v, "C": c, "T": t, "S": s, "K": k, "Q": q, "U": u, "E": e}


def post(api_base_url: str, payload):
    return httpx.post(f"{api_base_url}/api/robust-plan", json=payload, timeout=10)


# ---------- 小范围穷举判据 ----------


@pytest.mark.parametrize("seed", range(12))
def test_breakpoint_optimum_matches_exhaustive(api_base_url: str, seed):
    rng = random.Random(2024 + seed)
    for _ in range(10):
        payload = random_case(rng)
        expected = exhaustive(payload)
        assert expected is not None
        resp = post(api_base_url, {k: str(v) for k, v in payload.items()})
        assert resp.status_code == 200, (payload, resp.text)
        body = resp.json()
        assert body["n"] == expected["n"], payload
        assert Decimal(body["worstDeviation"]) == expected["worst"]
        assert Decimal(body["finalSugarLow"]) == expected["low"]
        assert Decimal(body["finalSugarHigh"]) == expected["high"]
        assert Decimal(body["dose"]) == expected["n"] * payload["Q"]
        assert Decimal(body["finalVolume"]) == payload["V"] + expected["n"] * payload["Q"]
        assert body["feasible"] == expected["feasible"]
        if expected["feasible"]:
            assert body["status"] == "ROBUST" and body["minToleranceGap"] is None
        else:
            assert body["status"] == "NO_ROBUST"
            assert Decimal(body["minToleranceGap"]) == expected["gap"]


def test_tie_prefers_smaller_n(api_base_url: str):
    # 精确构造 g(1)==g(2) 且同为全局最小：V=1,Q=1,S-T=2,U=1,T-C=3（×10000）
    payload = {
        "V": "0.0001", "C": "1", "T": "1.0003", "S": "1.0005",
        "K": "0.0015", "Q": "0.0001", "U": "0.0001", "E": "999",
    }
    assert exhaustive(payload)["n"] == 1
    body = post(api_base_url, payload).json()
    assert body["n"] == 1


# ---------- 三种业务结果 ----------


def test_robust_plan_mainline(api_base_url: str):
    payload = {**BASE_PAYLOAD, "Q": "10", "U": "0", "E": "0.5"}
    body = post(api_base_url, payload).json()
    assert body["feasible"] is True
    assert body["status"] == "ROBUST"
    assert body["message"] == "稳健刻度"
    n = body["n"]
    assert Decimal(body["dose"]) == n * Decimal("10")
    assert Decimal(body["finalVolume"]) <= Decimal("600")
    assert Decimal(body["finalSugarLow"]) == Decimal(body["finalSugarHigh"])  # U=0 退化为单点
    assert Decimal(body["worstDeviation"]) <= Decimal("0.5")
    assert body["minToleranceGap"] is None
    assert set(body["inputs"]) == {"V", "C", "T", "S", "K", "Q", "U", "E"}


def test_no_robust_shows_gap(api_base_url: str):
    payload = {"V": "500", "C": "5", "T": "8", "S": "30", "K": "560", "Q": "10", "U": "2", "E": "0"}
    body = post(api_base_url, payload).json()
    assert body["feasible"] is False
    assert body["status"] == "NO_ROBUST"
    assert Decimal(body["minToleranceGap"]) == Decimal(body["worstDeviation"]) > 0
    # 仍给出最优刻度与终态区间
    assert body["n"] is not None and Decimal(body["dose"]) > 0


def test_no_capacity_is_business_result(api_base_url: str):
    payload = {"V": "500", "C": "5", "T": "8", "S": "30", "K": "505", "Q": "10", "U": "1", "E": "0.1"}
    resp = post(api_base_url, payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "NO_CAPACITY"
    assert body["feasible"] is False
    assert body["n"] is None
    assert body["dose"] is None and body["worstDeviation"] is None and body["minToleranceGap"] is None


def test_exactly_one_tick_fits(api_base_url: str):
    # V+Q == K：等号允许，恰好一个刻度
    payload = {"V": "500", "C": "5", "T": "8", "S": "30", "K": "510", "Q": "10", "U": "1", "E": "99"}
    body = post(api_base_url, payload).json()
    assert body["n"] == 1 and Decimal(body["finalVolume"]) == Decimal(510)


# ---------- 超大范围不线性遍历 ----------


def test_huge_range_is_fast_and_optimal(api_base_url: str):
    payload = {
        "V": "1", "C": "0.0001", "T": "0.0002", "S": "0.0004",
        "K": "99999999999999999999999999999.9999",
        "Q": "0.0001", "U": "0.0001", "E": "0.5",
    }
    started = time.perf_counter()
    resp = post(api_base_url, payload)
    elapsed = time.perf_counter() - started
    assert resp.status_code == 200
    assert elapsed < 5.0  # 逐刻度扫描（n_max ~ 10^38）绝不可能在此时间内完成

    # 独立按断点定义复核最优（不逐刻度）
    V, C, T, S, K, Q, U, E = (_si(payload[name]) for name in (
        "V", "C", "T", "S", "K", "Q", "U", "E"))
    n_max = (K - V) // Q
    target = V * (T - C)
    cands = {1, n_max}
    for slope in (Q * (S + U - T), Q * (S - U - T), Q * (S - T)):
        f = target // slope
        cands |= {x for x in (f, f + 1) if 1 <= x <= n_max}

    def worst(n):
        p_low = target - n * Q * (S - U - T)
        p_high = n * Q * (S + U - T) - target
        return Fraction(max(p_low, p_high), V + n * Q)

    expected_n = min(sorted(cands), key=worst)
    assert resp.json()["n"] == expected_n


def test_astronomically_large_optimum(api_base_url: str):
    # 最优点本身在 ~5×10^29 处
    v, c, t, s, q, u = 10**24, 10000, 510000, 510001, 1, 0
    n_floor = int(Fraction(v * (t - c), q * (s - t)))
    k = v + (n_floor + 5) * q
    payload = {
        "V": str(Decimal(v) / SCALE), "C": "1", "T": "51", "S": "51.0001",
        "K": str(Decimal(k) / SCALE), "Q": "0.0001", "U": "0", "E": "0.0001",
    }
    started = time.perf_counter()
    body = post(api_base_url, payload).json()
    assert time.perf_counter() - started < 5.0
    assert body["n"] in (n_floor, n_floor + 1)


# ---------- 输入校验 ----------


def test_q_u_e_errors_in_order(api_base_url: str):
    resp = post(api_base_url, {**BASE_PAYLOAD, "Q": "0", "U": "-1", "E": "-1"})
    assert resp.status_code == 422
    assert [e["field"] for e in resp.json()["errors"]] == ["Q", "U", "E"]


@pytest.mark.parametrize("bad,field", [
    ("-1", "Q"), ("1.23456", "Q"), ("NaN", "Q"),
    ("-0.0001", "U"), ("1.23456", "U"),
    ("-0.0001", "E"), ("1.23456", "E"), ("abc", "E"),
])
def test_invalid_q_u_e_located(api_base_url: str, bad, field):
    payload = {**BASE_PAYLOAD, "Q": "10", "U": "0", "E": "0", field: bad}
    resp = post(api_base_url, payload)
    assert resp.status_code == 422
    assert any(e["field"] == field for e in resp.json()["errors"])


def test_u_interval_relations(api_base_url: str):
    # S-U == T：非法
    r1 = post(api_base_url, {"V": "500", "C": "5", "T": "8", "S": "10", "K": "600", "Q": "10", "U": "2", "E": "0"})
    assert r1.status_code == 422 and any(e["field"] == "U" for e in r1.json()["errors"])
    # S+U > 100：非法
    r2 = post(api_base_url, {"V": "500", "C": "5", "T": "8", "S": "99.9999", "K": "600", "Q": "10", "U": "0.0002", "E": "0"})
    assert r2.status_code == 422 and any(e["field"] == "U" for e in r2.json()["errors"])
    # S+U == 100：允许
    r3 = post(api_base_url, {"V": "500", "C": "5", "T": "8", "S": "98", "K": "600", "Q": "10", "U": "2", "E": "99"})
    assert r3.status_code == 200


def test_extra_field_rejected(api_base_url: str):
    resp = post(api_base_url, {**BASE_PAYLOAD, "Q": "10", "U": "0", "E": "0", "X": 1})
    assert resp.status_code == 422


def test_base_five_relations_still_validated(api_base_url: str):
    resp = post(api_base_url, {"V": "500", "C": "5", "T": "3", "S": "30", "K": "600", "Q": "10", "U": "0", "E": "0"})
    assert resp.status_code == 422
    assert any(e["field"] == "T" for e in resp.json()["errors"])


# ---------- 既有接口契约不变 ----------


def test_judge_contract_unchanged(api_base_url: str):
    resp = httpx.post(f"{api_base_url}/api/judge", json=BASE_PAYLOAD, timeout=10)
    assert resp.status_code == 200
    assert set(resp.json()) == {
        "verdict", "message", "dose", "finalVolume", "remainingCapacity", "excess", "inputs",
    }


def test_drain_plan_contract_unchanged(api_base_url: str):
    resp = httpx.post(
        f"{api_base_url}/api/drain-plan",
        json={"V": "500", "C": "5", "T": "8", "S": "30", "K": "550", "D": "20"},
        timeout=10,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "EXECUTABLE"
