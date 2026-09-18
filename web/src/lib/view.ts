/** 由真实 API 响应构建展示视图模型（纯函数，便于测试）。 */

import type {
  DrainPlanResponse,
  FieldErrorItem,
  FieldKey,
  JudgeResponse,
  RobustFieldKey,
  RobustPlanResponse,
} from './api';
import { DRAIN_FIELD, FIELD_KEYS, ROBUST_FIELDS } from './api';
import { formatDecimal } from './format';

export interface ResultRow {
  label: string;
  value: string;
  testId: string;
}

export interface ResultView {
  verdict: 'ALLOWED' | 'FORBIDDEN';
  verdictText: string;
  formula: string;
  rows: ResultRow[];
}

export function buildResultView(res: JudgeResponse): ResultView {
  const dose = formatDecimal(res.dose);
  const { V, C, T, S } = res.inputs;
  // 公式代入展示：操作数与结果均最多四位小数、去除无意义尾零
  const formula = `x = V×(T-C)/(S-T) = ${V}×(${T}-${C})/(${S}-${T}) = ${dose}`;
  const rows: ResultRow[] = [
    { label: '唯一补加量 x（毫升）', value: dose, testId: 'dose' },
    { label: '终态体积 V+x（毫升）', value: formatDecimal(res.finalVolume), testId: 'final-volume' },
  ];
  if (res.verdict === 'ALLOWED') {
    rows.push({
      label: '剩余容量（毫升）',
      value: formatDecimal(res.remainingCapacity ?? '0'),
      testId: 'remaining',
    });
  } else {
    rows.push({
      label: '超出容量（毫升）',
      value: formatDecimal(res.excess ?? '0'),
      testId: 'excess',
    });
  }
  return { verdict: res.verdict, verdictText: res.message, formula, rows };
}

export interface DrainPlanView {
  status: 'EXECUTABLE' | 'EXCEEDS_LIMIT';
  statusText: string;
  rows: ResultRow[];
}

export function buildDrainPlanView(res: DrainPlanResponse): DrainPlanView {
  const rows: ResultRow[] = [];
  if (res.status === 'EXECUTABLE') {
    // 可执行：最小排出量、排出后体积、补加量与恰好不超过容量的终态
    rows.push(
      { label: '最小排出量 d（毫升）', value: formatDecimal(res.minDrain), testId: 'drain-min' },
      {
        label: '排出后体积（毫升）',
        value: formatDecimal(res.volumeAfterDrain ?? '0'),
        testId: 'drain-volume-after',
      },
      { label: '排出后补加量（毫升）', value: formatDecimal(res.dose ?? '0'), testId: 'drain-dose' },
      {
        label: '终态体积（毫升）',
        value: formatDecimal(res.finalVolume ?? '0'),
        testId: 'drain-final-volume',
      },
    );
  } else {
    // 超出排出上限：只展示仍缺少的排出量，不呈现可执行剂量
    rows.push({
      label: '仍缺少的排出量（毫升）',
      value: formatDecimal(res.shortfall ?? '0'),
      testId: 'drain-shortfall',
    });
  }
  return { status: res.status, statusText: res.message, rows };
}

/** 把 422 错误列表拆分为字段级错误与全局消息。 */
export function mapFieldErrors(items: FieldErrorItem[]): {
  fieldErrors: Partial<Record<FieldKey, string>>;
  globalMessages: string[];
} {
  const fieldErrors: Partial<Record<FieldKey, string>> = {};
  const globalMessages: string[] = [];
  for (const item of items) {
    if (item.field && (FIELD_KEYS as readonly string[]).includes(item.field)) {
      fieldErrors[item.field as FieldKey] = item.message;
    } else {
      globalMessages.push(item.message);
    }
  }
  return { fieldErrors, globalMessages };
}

/** 腾容请求的 422 错误：D 定位到排出上限字段，五项回到主表单，其余进全局消息。 */
export function splitDrainErrors(items: FieldErrorItem[]): {
  fieldErrors: Partial<Record<FieldKey, string>>;
  drainFieldError: string | null;
  globalMessages: string[];
} {
  const fieldErrors: Partial<Record<FieldKey, string>> = {};
  const globalMessages: string[] = [];
  let drainFieldError: string | null = null;
  for (const item of items) {
    if (item.field === DRAIN_FIELD) {
      drainFieldError = item.message;
    } else if (item.field && (FIELD_KEYS as readonly string[]).includes(item.field)) {
      fieldErrors[item.field as FieldKey] = item.message;
    } else {
      globalMessages.push(item.message);
    }
  }
  return { fieldErrors, drainFieldError, globalMessages };
}

export interface RobustPlanView {
  status: RobustPlanResponse['status'];
  statusText: string;
  rows: ResultRow[];
}

/** 稳健刻度方案展示：可行时给出剂量、终态体积、终态糖度区间与最坏偏差；
 * 无稳健刻度时追加最小容差缺口；容量放不下一个刻度时只展示结论。 */
export function buildRobustPlanView(res: RobustPlanResponse): RobustPlanView {
  const rows: ResultRow[] = [];
  if (res.status === 'NO_CAPACITY') {
    return { status: res.status, statusText: res.message, rows };
  }
  const n = res.n as number;
  rows.push({ label: `投加剂量（${n} 个刻度，毫升）`, value: formatDecimal(res.dose ?? '0'), testId: 'robust-dose' });
  rows.push({
    label: '终态体积（毫升）',
    value: formatDecimal(res.finalVolume ?? '0'),
    testId: 'robust-final-volume',
  });
  rows.push({
    label: '终态糖度区间（%）',
    value: `${formatDecimal(res.finalSugarLow ?? '0')} ~ ${formatDecimal(res.finalSugarHigh ?? '0')}`,
    testId: 'robust-sugar-range',
  });
  rows.push({
    label: '最坏偏差（%）',
    value: formatDecimal(res.worstDeviation ?? '0'),
    testId: 'robust-worst',
  });
  if (res.status === 'NO_ROBUST') {
    rows.push({
      label: '最小容差缺口（%）',
      value: formatDecimal(res.minToleranceGap ?? '0'),
      testId: 'robust-gap',
    });
  }
  return { status: res.status, statusText: res.message, rows };
}

/** 稳健刻度请求的 422 错误：Q/U/E 定位到刻度表单，五项回到主表单，其余进全局消息。 */
export function splitRobustErrors(items: FieldErrorItem[]): {
  fieldErrors: Partial<Record<FieldKey, string>>;
  robustFieldErrors: Partial<Record<RobustFieldKey, string>>;
  globalMessages: string[];
} {
  const fieldErrors: Partial<Record<FieldKey, string>> = {};
  const robustFieldErrors: Partial<Record<RobustFieldKey, string>> = {};
  const globalMessages: string[] = [];
  for (const item of items) {
    if (item.field && (ROBUST_FIELDS as readonly string[]).includes(item.field)) {
      robustFieldErrors[item.field as RobustFieldKey] = item.message;
    } else if (item.field && (FIELD_KEYS as readonly string[]).includes(item.field)) {
      fieldErrors[item.field as FieldKey] = item.message;
    } else {
      globalMessages.push(item.message);
    }
  }
  return { fieldErrors, robustFieldErrors, globalMessages };
}
