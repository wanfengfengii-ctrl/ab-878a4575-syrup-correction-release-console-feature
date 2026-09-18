/** 与判定 API 的交互与类型定义。 */

export const FIELD_KEYS = ['V', 'C', 'T', 'S', 'K'] as const;
export type FieldKey = (typeof FIELD_KEYS)[number];

/** 腾容方案的排出上限字段名 */
export const DRAIN_FIELD = 'D' as const;
export type DrainFieldKey = typeof DRAIN_FIELD;

/** 稳健刻度方案的三项参数字段名 */
export const ROBUST_FIELDS = ['Q', 'U', 'E'] as const;
export type RobustFieldKey = (typeof ROBUST_FIELDS)[number];

export interface JudgeResponse {
  verdict: 'ALLOWED' | 'FORBIDDEN';
  message: string;
  /** 唯一补加量 x（完整精度十进制字符串，mL） */
  dose: string;
  /** 终态体积 V+x（完整精度，mL） */
  finalVolume: string;
  /** 剩余容量（完整精度，mL），放行时给出 */
  remainingCapacity: string | null;
  /** 超出容量（完整精度，mL），禁止时给出 */
  excess: string | null;
  /** 规范化后的输入回显 */
  inputs: Record<FieldKey, string>;
}

export type DrainStatus = 'EXECUTABLE' | 'EXCEEDS_LIMIT';

export interface DrainPlanResponse {
  status: DrainStatus;
  message: string;
  /** 恢复补加所需的最小排出量 d（完整精度，mL） */
  minDrain: string;
  /** 排出后体积 V-d（完整精度，mL），可执行时给出 */
  volumeAfterDrain: string | null;
  /** 排出后的糖浆补加量（完整精度，mL），可执行时给出 */
  dose: string | null;
  /** 终态体积（完整精度，mL），可执行时给出，恰好不超过容量 */
  finalVolume: string | null;
  /** 仍缺少的排出量 d-D（完整精度，mL），超出排出上限时给出 */
  shortfall: string | null;
  /** 规范化后的输入回显（含 D） */
  inputs: Record<FieldKey | DrainFieldKey, string>;
}

export type RobustStatus = 'ROBUST' | 'NO_ROBUST_MARK';

export interface RobustPlanResponse {
  status: RobustStatus;
  message: string;
  /** 最优刻度数 n（正整数），无稳健刻度时为 null */
  n: number | null;
  /** 剂量 nQ（完整精度，mL），稳健时给出 */
  dose: string | null;
  /** 糖浆取 S-U 时的终态糖度（完整精度，%），稳健时给出 */
  finalConcentrationLow: string | null;
  /** 糖浆取 S+U 时的终态糖度（完整精度，%），稳健时给出 */
  finalConcentrationHigh: string | null;
  /** 最坏偏差（完整精度，%），稳健时给出 */
  worstDeviation: string | null;
  /** 最小容差缺口 最优偏差-E（完整精度，%），无稳健刻度时给出（无可行刻度时为 null） */
  toleranceGap: string | null;
  /** 规范化后的输入回显（含 Q、U、E） */
  inputs: Record<FieldKey | RobustFieldKey, string>;
}

export interface FieldErrorItem {
  field: FieldKey | DrainFieldKey | RobustFieldKey | null;
  message: string;
}

/** 输入校验失败（HTTP 422）：整单拒绝，携带字段级错误。 */
export class JudgeRequestError extends Error {
  readonly fieldErrors: FieldErrorItem[];

  constructor(detail: string, fieldErrors: FieldErrorItem[]) {
    super(detail);
    this.name = 'JudgeRequestError';
    this.fieldErrors = fieldErrors;
  }
}

const API_BASE: string = (import.meta.env.VITE_API_BASE as string | undefined) ?? '';

async function postJson<T>(path: string, payload: unknown): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
  } catch {
    throw new Error('无法连接判定服务，请稍后重试');
  }
  const body: unknown = await response.json().catch(() => null);
  if (response.ok) {
    return body as T;
  }
  const errBody = body as { detail?: string; errors?: FieldErrorItem[] } | null;
  if (response.status === 422 && errBody && Array.isArray(errBody.errors)) {
    throw new JudgeRequestError(errBody.detail ?? '输入校验失败，已整单拒绝', errBody.errors);
  }
  throw new Error(`判定服务异常（HTTP ${response.status}）`);
}

export async function judgeDose(values: Record<FieldKey, string>): Promise<JudgeResponse> {
  return postJson<JudgeResponse>('/api/judge', values);
}

/** 生成腾容方案：复用原判定的五项输入 + 本次最多可排出量 D。 */
export async function requestDrainPlan(
  inputs: Record<FieldKey, string>,
  drainLimit: string,
): Promise<DrainPlanResponse> {
  return postJson<DrainPlanResponse>('/api/drain-plan', { ...inputs, [DRAIN_FIELD]: drainLimit });
}

/** 生成稳健刻度方案：复用允许补加判定的五项输入 + Q（单刻度量）、U（糖度波动）、E（终态容差）。 */
export async function requestRobustPlan(
  inputs: Record<FieldKey, string>,
  params: Record<RobustFieldKey, string>,
): Promise<RobustPlanResponse> {
  return postJson<RobustPlanResponse>('/api/robust-plan', { ...inputs, ...params });
}
