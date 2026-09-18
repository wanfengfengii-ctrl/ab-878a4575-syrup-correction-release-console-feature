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
    现场泵按固定刻度投料，剂量为 nQ（n 为正整数）。糖浆实际糖度落在
    区间 [S-U, S+U]，对两端点 s-=S-U、s+=S+U 计算终态糖度
        F_s(n) = (V·C + nQ·s)/(V + nQ)
    在容量刻度约束 V+nQ <= K 内，选择最坏偏差 max(|F_s--T|, |F_s+-T|)
    最小的 n，同值取较小 n；最优偏差 <= E 即稳健，否则给出容差缺口。
    算法不逐刻度扫描：F_s 关于剂量 x 单调，两端点各有唯一命中 T 的实数剂量
    x_s = V×(T-C)/(s-T)（下端点 x_low 较大、上端点 x_high 较小），两偏差分支
    T-F_s-（随 x 递减）与 F_s+-T（随 x 递增）在 x0 = V×(T-C)/(S-T) 处相交。
    由于 T-F_s- 恒递减、F_s+-T 恒递增，g=max(T-F_s-, F_s+-T) 恰为最坏绝对偏差
    （按命中点分三段取号），在 x0 左侧递减、右侧递增；故只需评估容量上界、两端点
    命中 T、偏差分支相交处这三类实数断点的相邻整数及边界刻度，结果与穷举定义的
    全局最优一致。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, localcontext

from .schemas import (
    FIELD_NAMES,
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
NO_ROBUST_MARK = "NO_ROBUST_MARK"
ROBUST_MESSAGES = {ROBUST: "稳健刻度", NO_ROBUST_MARK: "无稳健刻度"}

# decimal 计算精度（有效数字位数），远高于展示所需的四位小数
COMPUTE_PRECISION = 50


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
        "inputs": {name: _strip(getattr(req, name)) for name in FIELD_NAMES + ("D",)},
    }


def _validate_robust_params(req: RobustPlanRequest) -> None:
    """稳健方案三项参数关系校验：Q>0、U>=0、S-U>T、S+U<=100、E>=0。

    按 Q、U、E 顺序收集全部违规并定位字段（U 可同时产生多条错误）。
    """
    errors: list[FieldError] = []
    if req.Q <= 0:
        errors.append(FieldError("Q", "单刻度量 Q 必须大于 0"))
    if req.U < 0:
        errors.append(FieldError("U", "糖度波动 U 不能为负数"))
    if req.S - req.U <= req.T:
        errors.append(FieldError("U", "波动下端点糖度 S-U 必须大于目标糖度 T"))
    if req.S + req.U > 100:
        errors.append(FieldError("U", "波动上端点糖度 S+U 不能超过 100"))
    if req.E < 0:
        errors.append(FieldError("E", "终态容差 E 不能为负数"))
    if errors:
        raise JudgeRejected(errors)


def _floor_int(value: Decimal) -> int:
    """Decimal 向下取整为 int（value 非负且量级有限）。"""
    return int(value.to_integral_value(rounding="ROUND_FLOOR"))


def robust_plan(req: RobustPlanRequest) -> dict:
    """在固定刻度 nQ 下求最坏端点偏差最小的稳健刻度，不改写 /api/judge 判定。

    复用判定五项的关系校验；Q/U/E 非法时抛出 JudgeRejected 整单拒绝。
    容量放不下一个刻度（V+Q>K）时返回业务结果（无稳健刻度），不报字段错误。
    """
    _validate_relations(req)
    _validate_robust_params(req)
    V, C, T, S, K, Q, U, E = (
        req.V,
        req.C,
        req.T,
        req.S,
        req.K,
        req.Q,
        req.U,
        req.E,
    )
    s_low = S - U
    s_high = S + U
    with localcontext() as ctx:
        ctx.prec = COMPUTE_PRECISION

        def dev_parts(n: int) -> tuple[Decimal, Decimal, Decimal, Decimal]:
            """给定正整数刻度数，返回 (下端终态, 上端终态, 下端偏差T-F, 上端偏差F-T)。"""
            x = n * Q
            vol = V + x
            f_low = (V * C + x * s_low) / vol
            f_high = (V * C + x * s_high) / vol
            return f_low, f_high, T - f_low, f_high - T

        # 容量放不下一个刻度：无可行刻度，属业务结果而非输入错误
        if V + Q > K:
            return _robust_empty_result(req, None)

        capacity = K - V
        n_max = _floor_int(capacity / Q)  # 向下取整
        # 极端量级下除法末位可能舍入，用精确乘法回校容量边界 V+nQ<=K（等号允许）
        while (n_max + 1) * Q <= capacity:
            n_max += 1
        while n_max * Q > capacity:
            n_max -= 1  # n_max >= 1：V+Q<=K 已保证

        # 实数断点（剂量 x，非刻度）：
        #   两端点命中 T：x_s = V×(T-C)/(s-T)，欠/过量分支各自在此取零
        x_low = V * (T - C) / (s_low - T)    # 下端点欠量分支 T-F_- 在此取零
        x_high = V * (T - C) / (s_high - T)  # 上端点过量分支 F_+-T 在此取零
        #   偏差分支相交处：T-F_- = F_+-T  ⟺  (F_-+F_+)/2 = T，解为
        #   x0 = V×(T-C)/(S-T)（按名义糖度 S）。x_high < x0 < x_low，
        #   g(x)=max(T-F_-,F_+-T) 在 x0 左侧递减、右侧递增，唯一最小值在 x0。
        x_cross = V * (T - C) / (S - T)

        def candidates_at(x: Decimal) -> list[int]:
            """实数剂量断点 x 相邻的可行正整数刻度。"""
            r = x / Q
            lo = _floor_int(r)
            ns = {lo, lo + 1}
            return [n for n in ns if 1 <= n <= n_max]

        # 仅评估各实数断点的相邻整数与边界刻度，绝不逐刻度扫描
        candidate_ns = {1, n_max}
        for br in (x_high, x_cross, x_low):
            candidate_ns.update(candidates_at(br))

        best_n: int | None = None
        best_dev: Decimal | None = None
        best_low = best_high = None
        for n in sorted(candidate_ns):
            f_low, f_high, under, over = dev_parts(n)
            dev = under if under >= over else over  # max(T-F_-, F_+-T)
            # 同值取较小 n：候选按升序评估，仅严格更优才替换
            if best_dev is None or dev < best_dev:
                best_n, best_dev = n, dev
                best_low, best_high = f_low, f_high

        gap = best_dev - E
        if best_dev <= E:
            return {
                "status": ROBUST,
                "message": ROBUST_MESSAGES[ROBUST],
                "n": best_n,
                "dose": _plain(best_n * Q),
                "finalConcentrationLow": _plain(best_low),
                "finalConcentrationHigh": _plain(best_high),
                "worstDeviation": _plain(best_dev),
                "toleranceGap": None,
                "inputs": _robust_inputs(req),
            }
        return _robust_empty_result(req, gap)


def _robust_inputs(req: RobustPlanRequest) -> dict:
    """规范化后的输入回显（判定五项 + Q/U/E，去除无意义尾零）。"""
    return {name: _strip(getattr(req, name)) for name in FIELD_NAMES + ("Q", "U", "E")}


def _robust_empty_result(req: RobustPlanRequest, gap: Decimal | None) -> dict:
    """构造无稳健刻度业务结果：不给剂量与终态区间，只给最小容差缺口。

    容量连一个刻度都放不下时不存在可行刻度，缺口亦无从计算，记为 None。
    """
    return {
        "status": NO_ROBUST_MARK,
        "message": ROBUST_MESSAGES[NO_ROBUST_MARK],
        "n": None,
        "dose": None,
        "finalConcentrationLow": None,
        "finalConcentrationHigh": None,
        "worstDeviation": None,
        "toleranceGap": _plain(gap) if gap is not None else None,
        "inputs": _robust_inputs(req),
    }



