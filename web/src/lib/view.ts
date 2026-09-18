/** 由真实 API 响应构建展示视图模型（纯函数，便于测试）。 */

import type {
  DrainPlanResponse,
  FieldErrorItem,
  FieldKey,
  JudgeResponse,
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

export interface RobustPlanView {
  status: 'ROBUST' | 'NO_ROBUST_MARK';
  statusText: string;
  rows: ResultRow[];
}

export function buildRobustPlanView(res: RobustPlanResponse): RobustPlanView {
  const rows: ResultRow[] = [];
  if (res.status === 'ROBUST') {
    // 稳健：剂量 nQ、终态糖度区间 [F_-, F_+] 与最坏偏差
    rows.push(
      {
        label: `剂量 nQ（${res.n ?? ''} 个刻度，毫升）`,
        value: formatDecimal(res.dose ?? '0'),
        testId: 'robust-dose',
      },
      {
        label: '终态糖度区间（%）',
        value: `${formatDecimal(res.finalConcentrationLow ?? '0')} ~ ${formatDecimal(
          res.finalConcentrationHigh ?? '0',
        )}`,
        testId: 'robust-range',
      },
      {
        label: '最坏偏差（%）',
        value: formatDecimal(res.worstDeviation ?? '0'),
        testId: 'robust-worst',
      },
    );
  } else {
    // 无稳健刻度：只显示最小容差缺口（容量放不下一个刻度时缺口无从计算）
    rows.push({
      label: '最小容差缺口（%）',
      value: res.toleranceGap === null ? '无可行刻度' : formatDecimal(res.toleranceGap),
      testId: 'robust-gap',
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

/** 稳健方案请求的 422 错误：Q/U/E 定位到方案参数，五项回到主表单，其余进全局消息。 */
export function splitRobustErrors(items: FieldErrorItem[]): {
  fieldErrors: Partial<Record<FieldKey, string>>;
  robustFieldErrors: Partial<Record<string, string>>;
  globalMessages: string[];
} {
  const fieldErrors: Partial<Record<FieldKey, string>> = {};
  const robustFieldErrors: Partial<Record<string, string>> = {};
  const globalMessages: string[] = [];
  for (const item of items) {
    if (item.field && (ROBUST_FIELDS as readonly string[]).includes(item.field)) {
      robustFieldErrors[item.field] = item.message;
    } else if (item.field && (FIELD_KEYS as readonly string[]).includes(item.field)) {
      fieldErrors[item.field as FieldKey] = item.message;
    } else {
      globalMessages.push(item.message);
    }
  }
  return { fieldErrors, robustFieldErrors, globalMessages };
}
