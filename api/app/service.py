"""补加判定核心逻辑。

质量守恒（液体密度相同，按体积折算）：
    V·C + x·S = (V + x)·T   =>   x = V×(T-C)/(S-T)

判定使用完整精度的计算值，绝不使用经展示格式化处理后的数值：
    V + x <= K  → 允许补加（等于容量也允许）
    V + x >  K  → 禁止补加

腾容方案（禁止补加后由操作员发起，不改写原判定）：
    按排出料液糖度仍为 C 的业务假设，排出 d mL 后罐内为 (V-d, C)，
    再补加恰好恢复到容量上限：终态体积恰为 K、糖度恰为 T。
        (V-d)·C + (K-(V-d))·S = K·T   =>   d = V - K×(S-T)/(S-C)
    d 即恢复补加所需的最小排出量；排出后的糖浆剂量仍按原质量守恒公式计算。
    以完整精度比较 d 与本次最多可排出量 D：
    d <= D  → 可执行（终态恰好不超过容量）
    d >  D  → 超出排出上限（仍缺少 d-D，不给出可执行剂量）

稳健刻度方案（允许补加后由操作员发起，不改写原判定）：
    现场按固定刻度投料，剂量只能取 nQ（n 为正整数）。糖浆实际糖度在
    [S-U, S+U] 内波动时，对区间两个端点计算终态糖度：
        F(s') = (V·C + nQ·s') / (V+nQ)
    下界端点终态最低 F(S-U) ≤ T，上界端点终态最高 F(S+U) ≥ T，
    故两端点对 T 的偏差（记刻度单位下的精确整数量）为
        Pd = V(T-C) - nQ((S-U)-T)   （T 减下界终态，随 n 单调下降）
        Pe = nQ((S+U)-T) - V(T-C)   （上界终态减 T，随 n 单调上升）
    最坏偏差 g(n) = max(Pd, Pe)/(V+nQ)，呈 V 形：先由 Pe 支下降、
    经 Pd=0（下界命中 T）、两支交点（最坏偏差谷底）、Pe=0（上界命中 T），
    再由 Pd 支上升。离散最优只可能出现在容量上界刻度 n_max=floor((K-V)/Q)
    与这三个实数断点的相邻整数处，因此只评估至多 8 个候选刻度，
    绝不逐刻度扫描；候选间以精确整数交叉相乘比较 g，同值取较小 n。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, localcontext

from .schemas import (
    ALL_FIELD_NAMES,
    FIELD_NAMES,
    ROBUST_FIELDS,
    DrainPlanRequest,
    JudgeRequest,
    RobustPlanRequest,
)

ALLOWED = "ALLOWED"
FORBIDDEN = "FORBIDDEN"
VERDICT_MESSAGES = {ALLOWED: "允许补加", FORBIDDEN: "禁止补加"}

EXECUTABLE = "EXECUTABLE"
EXCEEDS_LIMIT = "EXCEEDS_LIMIT"
DRAIN_MESSAGES = {EXECUTABLE: "可执行", EXCEEDS_LIMIT: "超出排出上限"}

ROBUST = "ROBUST"
NO_ROBUST = "NO_ROBUST"
NO_CAPACITY = "NO_CAPACITY"
ROBUST_MESSAGES = {
    ROBUST: "稳健刻度",
    NO_ROBUST: "无稳健刻度",
    NO_CAPACITY: "容量放不下一个刻度",
}

# decimal 计算精度（有效数字位数），远高于展示所需的四位小数
COMPUTE_PRECISION = 50

# 输入最多四位小数：全部乘以 10000 即化为精确整数，断点取整与候选比较
# 因此都可以用整数精确完成，不受 decimal 有效数字位数限制（超大范围也不丢精度）
SCALE = 10000
SCALE_DEC = Decimal(SCALE)


@dataclass
class FieldError:
    field: str | None  # None 表示不定位到具体字段的全局错误
    message: str


class JudgeRejected(Exception):
    """输入校验失败，整单拒绝。"""

    def __init__(self, errors: list[FieldError]) -> None:
        super().__init__("输入校验失败，已整单拒绝")
        self.errors = errors


def _plain(value: Decimal) -> str:
    """完整精度十进制字符串（不使用科学计数法）。"""
    return format(value, "f")


def _strip(value: Decimal) -> str:
    """输入回显规范化：去除无意义尾零。"""
    return format(value.normalize(), "f")


def _validate_relations(req: JudgeRequest) -> None:
    """关系校验：0<C<T<S≤100、V>0、K>0、V≤K。收集全部违规并定位字段。"""
    errors: list[FieldError] = []
    V, C, T, S, K = req.V, req.C, req.T, req.S, req.K
    if C <= 0:
        errors.append(FieldError("C", "当前糖度 C 必须大于 0"))
    if T <= C:
        errors.append(FieldError("T", "目标糖度 T 必须大于当前糖度 C"))
    if S <= T:
        errors.append(FieldError("S", "糖浆糖度 S 必须大于目标糖度 T"))
    if S > 100:
        errors.append(FieldError("S", "糖浆糖度 S 不能超过 100"))
    if V <= 0:
        errors.append(FieldError("V", "当前体积 V 必须大于 0"))
    if K <= 0:
        errors.append(FieldError("K", "罐体容量 K 必须大于 0"))
    if V > K:
        errors.append(FieldError("V", "当前体积 V 不能超过罐体容量 K"))
    if errors:
        raise JudgeRejected(errors)


def judge(req: JudgeRequest) -> dict:
    """计算唯一补加量并判定容量。关系错误时抛出 JudgeRejected 整单拒绝。"""
    _validate_relations(req)
    V, C, T, S, K = req.V, req.C, req.T, req.S, req.K
    with localcontext() as ctx:
        ctx.prec = COMPUTE_PRECISION
        dose = V * (T - C) / (S - T)
        final_volume = V + dose
        # 判定使用未因展示格式改变的完整精度计算值
        allowed = final_volume <= K
        remaining = K - final_volume if allowed else None
        excess = final_volume - K if not allowed else None
    verdict = ALLOWED if allowed else FORBIDDEN
    return {
        "verdict": verdict,
        "message": VERDICT_MESSAGES[verdict],
        "dose": _plain(dose),
        "finalVolume": _plain(final_volume),
        "remainingCapacity": _plain(remaining) if remaining is not None else None,
        "excess": _plain(excess) if excess is not None else None,
        "inputs": {name: _strip(getattr(req, name)) for name in FIELD_NAMES},
    }


def _validate_drain_limit(req: DrainPlanRequest) -> None:
    """排出上限 D 的关系校验：非负且必须小于当前体积 V。"""
    errors: list[FieldError] = []
    if req.D < 0:
        errors.append(FieldError("D", "排出上限 D 不能为负数"))
    if req.D >= req.V:
        errors.append(FieldError("D", "排出上限 D 必须小于当前体积 V"))
    if errors:
        raise JudgeRejected(errors)


def drain_plan(req: DrainPlanRequest) -> dict:
    """计算恢复补加所需的最小排出量并判定是否超出排出上限。

    复用判定五项的关系校验；任何输入非法时抛出 JudgeRejected 整单拒绝。
    本函数只产出方案，绝不改写 /api/judge 的判定结论。
    """
    _validate_relations(req)
    _validate_drain_limit(req)
    V, C, T, S, K, D = req.V, req.C, req.T, req.S, req.K, req.D
    with localcontext() as ctx:
        ctx.prec = COMPUTE_PRECISION
        # 排出料液糖度仍为 C：反解终态恰为 (K, T) 所需的最小排出量
        min_drain = V - K * (S - T) / (S - C)
        # d <= 0 ⟺ V+x <= K：判定实为允许补加，无需排出，不生成腾容方案
        if min_drain <= 0:
            raise JudgeRejected([FieldError(None, "当前判定允许补加，无需腾容方案")])
        # 以完整精度比较最小排出量与本次最多可排出量
        executable = min_drain <= D
        if executable:
            volume_after = V - min_drain
            # 排出后的糖浆剂量仍按原质量守恒公式计算
            dose = volume_after * (T - C) / (S - T)
            final_volume = volume_after + dose
            shortfall = None
        else:
            volume_after = dose = final_volume = None
            shortfall = min_drain - D
    status = EXECUTABLE if executable else EXCEEDS_LIMIT
    return {
        "status": status,
        "message": DRAIN_MESSAGES[status],
        "minDrain": _plain(min_drain),
        "volumeAfterDrain": _plain(volume_after) if volume_after is not None else None,
        "dose": _plain(dose) if dose is not None else None,
        "finalVolume": _plain(final_volume) if final_volume is not None else None,
        "shortfall": _plain(shortfall) if shortfall is not None else None,
        "inputs": {name: _strip(getattr(req, name)) for name in ALL_FIELD_NAMES},
    }


def _validate_robust_inputs(req: RobustPlanRequest) -> None:
    """稳健刻度三项输入的关系校验：Q>0、U≥0、S-U>T、S+U≤100、E≥0。

    按 Q、U、E 的字段顺序收集全部违规并定位字段，一次性返回。
    """
    errors: list[FieldError] = []
    Q, U, E = req.Q, req.U, req.E
    if Q <= 0:
        errors.append(FieldError("Q", "单刻度量 Q 必须大于 0"))
    if U < 0:
        errors.append(FieldError("U", "糖度波动 U 不能为负数"))
    if req.S - U <= req.T:
        errors.append(FieldError("U", "糖度区间下界 S-U 必须大于目标糖度 T"))
    if req.S + U > 100:
        errors.append(FieldError("U", "糖度区间上界 S+U 不能超过 100"))
    if E < 0:
        errors.append(FieldError("E", "终态容差 E 不能为负数"))
    if errors:
        raise JudgeRejected(errors)


def _scaled(value: Decimal) -> int:
    """四位小数以内的 Decimal 精确化为 ×10000 的整数（四舍五入不发生：已限四位）。"""
    return int(value.scaleb(4).to_integral_value())


def robust_plan(req: RobustPlanRequest) -> dict:
    """在容量允许的固定刻度中求最坏糖度偏差最小的刻度，绝不逐刻度扫描。

    复用判定五项的关系校验；Q/U/E 非法时按 Q、U、E 顺序抛出 JudgeRejected。
    本函数只产出方案，绝不改写 /api/judge 的判定结论。
    容量连一个刻度都放不下（V+Q>K）时返回业务结果（NO_CAPACITY），不视为非法输入。
    """
    _validate_relations(req)
    _validate_robust_inputs(req)
    V, C, T, S, K, Q, U, E = req.V, req.C, req.T, req.S, req.K, req.Q, req.U, req.E

    # 全部输入 ×10000 化为精确整数（Python 大整数无精度上限，超大范围也精确）
    v, c, t, s = _scaled(V), _scaled(C), _scaled(T), _scaled(S)
    k, q, u, e = _scaled(K), _scaled(Q), _scaled(U), _scaled(E)

    # 容量上界刻度：V+nQ <= K 的最大正整数 n；一个刻度都放不下属于业务结果
    n_max = (k - v) // q
    if n_max < 1:
        return {
            "feasible": False,
            "status": NO_CAPACITY,
            "message": ROBUST_MESSAGES[NO_CAPACITY],
            "n": None,
            "dose": None,
            "finalVolume": None,
            "finalSugarLow": None,
            "finalSugarHigh": None,
            "worstDeviation": None,
            "minToleranceGap": None,
            "inputs": {
                name: _strip(getattr(req, name)) for name in (*FIELD_NAMES, *ROBUST_FIELDS)
            },
        }

    # 偏差两项的量纲都是 (×1e4 mL)·(×1e4 %)，除以 ×1e4 mL 的体积分母后
    # 恰为 ×1e4 % 的糖度，故最后统一除以 SCALE 回到真实糖度，全程无需浮点。
    target = v * (t - c)  # V(T-C)：n=0 时把糖度抬到 T 所需的“糖量缺口”
    low_slope = q * (s - u - t)  # nQ((S-U)-T)：每刻度相对下界端点的糖量贡献
    high_slope = q * (s + u - t)  # nQ((S+U)-T)：每刻度相对上界端点的糖量贡献
    nominal_slope = q * (s - t)  # nQ(S-T)：两偏差支交点（标称端点命中 T）的断点用

    # 三个实数断点（连续意义上最坏偏差 V 形的结构变化点）：
    #   下界命中 T：Pd=0  =>  n = V(T-C)/(Q((S-U)-T))
    #   两支交点：  Pd=Pe =>  n = V(T-C)/(Q(S-T))
    #   上界命中 T：Pe=0  =>  n = V(T-C)/(Q((S+U)-T))
    # 三者均为严格正有理数且单调递减排列；离散最优只可能落在其相邻整数或容量边界
    candidates: set[int] = {1, n_max}
    for slope in (high_slope, low_slope, nominal_slope):
        floor_n = target // slope
        for n in (floor_n, floor_n + 1):
            if 1 <= n <= n_max:
                candidates.add(n)

    def deviation_parts(n: int) -> tuple[int, int]:
        """返回 (偏差分子 P, 体积分母 D)：最坏偏差 g(n)=P/D（×10000 的糖度单位）。"""
        p_low = target - n * low_slope  # T - F(S-U)
        p_high = n * high_slope - target  # F(S+U) - T
        return max(p_low, p_high), v + n * q

    # 在候选中取 g 最小者：按 n 升序评估，整数交叉相乘精确比较（绝不依赖浮点）；
    # 严格小于才更新，g 同值时先评估的较小 n 自然胜出
    best_n = min(candidates)
    best_p, best_d = deviation_parts(best_n)
    for n in sorted(candidates):
        if n == best_n:
            continue
        p, d = deviation_parts(n)
        if p * best_d < best_p * d:
            best_n, best_p, best_d = n, p, d

    # 容差判定同样用精确整数交叉相乘：g* <= E  ⟺  P <= e_scale·D
    feasible = best_p <= e * best_d

    # 展示值回到真实糖度量纲（除以 10000）；除不尽时以 Decimal 50 位计算完整精度。
    # 终态糖度区间取两个端点的真实终态 F(S-U)、F(S+U)，区间未必以 T 为中心
    # （剂量过小时两端点都可能低于 T），最坏偏差仍是二者到 T 距离的最大者。
    with localcontext() as ctx:
        ctx.prec = COMPUTE_PRECISION
        dose = best_n * Q
        final_volume = V + dose
        worst = Decimal(best_p) / Decimal(best_d) / SCALE_DEC
        final_low = Decimal(v * c + best_n * q * (s - u)) / Decimal(best_d) / SCALE_DEC
        final_high = Decimal(v * c + best_n * q * (s + u)) / Decimal(best_d) / SCALE_DEC
        # 容差缺口按精确差值 (P-e·D)/(D·10000) 一次性舍入，避免对已舍入 worst 再做减法
        gap = (
            None
            if feasible
            else Decimal(best_p - e * best_d) / Decimal(best_d) / SCALE_DEC
        )

    status = ROBUST if feasible else NO_ROBUST
    return {
        "feasible": feasible,
        "status": status,
        "message": ROBUST_MESSAGES[status],
        "n": best_n,
        "dose": _plain(dose),
        "finalVolume": _plain(final_volume),
        "finalSugarLow": _plain(final_low),
        "finalSugarHigh": _plain(final_high),
        "worstDeviation": _plain(worst),
        "minToleranceGap": _plain(gap) if gap is not None else None,
        "inputs": {name: _strip(getattr(req, name)) for name in (*FIELD_NAMES, *ROBUST_FIELDS)},
    }
