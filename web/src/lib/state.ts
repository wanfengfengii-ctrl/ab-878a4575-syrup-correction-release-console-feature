/** 判定台状态机：非法输入整单拒绝时必须清除旧结论。
 *
 * 腾容方案状态独立于判定结论：非法 D 或请求失败只清除旧方案，
 * 绝不清除或覆盖原判定结论，腾容结果也不会被误作原始判定。
 */

import type { DrainPlanResponse, FieldKey, JudgeResponse } from './api';

export interface ConsoleState {
  result: JudgeResponse | null;
  fieldErrors: Partial<Record<FieldKey, string>>;
  globalError: string | null;
  submitting: boolean;
  /** 腾容方案（仅挂在禁止补加结论下） */
  drainPlan: DrainPlanResponse | null;
  /** 排出上限 D 的字段级错误 */
  drainFieldError: string | null;
  /** 腾容请求级错误（服务异常等） */
  drainGlobalError: string | null;
  drainSubmitting: boolean;
}

export const initialState: ConsoleState = {
  result: null,
  fieldErrors: {},
  globalError: null,
  submitting: false,
  drainPlan: null,
  drainFieldError: null,
  drainGlobalError: null,
  drainSubmitting: false,
};

/** 主判定重新得出结论（无论成败）时，腾容方案一律作废。 */
const clearedDrain = {
  drainPlan: null,
  drainFieldError: null,
  drainGlobalError: null,
  drainSubmitting: false,
} as const;

export type ConsoleAction =
  | { type: 'submit/start' }
  | { type: 'submit/success'; result: JudgeResponse }
  | { type: 'submit/rejected'; fieldErrors: Partial<Record<FieldKey, string>>; message: string }
  | { type: 'submit/failed'; message: string }
  | { type: 'drain/start' }
  | { type: 'drain/success'; plan: DrainPlanResponse }
  | {
      type: 'drain/rejected';
      fieldErrors: Partial<Record<FieldKey, string>>;
      drainFieldError: string | null;
      message: string;
    }
  | { type: 'drain/failed'; message: string };

export function consoleReducer(state: ConsoleState, action: ConsoleAction): ConsoleState {
  switch (action.type) {
    case 'submit/start':
      return { ...state, submitting: true, globalError: null };
    case 'submit/success':
      return {
        ...state,
        ...clearedDrain,
        submitting: false,
        result: action.result,
        fieldErrors: {},
        globalError: null,
      };
    case 'submit/rejected':
      // 整单拒绝：定位字段并清除旧结论
      return {
        ...state,
        ...clearedDrain,
        submitting: false,
        result: null,
        fieldErrors: action.fieldErrors,
        globalError: action.message,
      };
    case 'submit/failed':
      // 请求失败同样清除旧结论，避免展示过期判定
      return {
        ...state,
        ...clearedDrain,
        submitting: false,
        result: null,
        globalError: action.message,
      };
    case 'drain/start':
      return { ...state, drainSubmitting: true, drainGlobalError: null };
    case 'drain/success':
      // 方案只挂在结论之下，绝不动原判定
      return {
        ...state,
        drainSubmitting: false,
        drainPlan: action.plan,
        drainFieldError: null,
        drainGlobalError: null,
      };
    case 'drain/rejected':
      // 非法 D：定位字段、清除旧方案，但保留原禁止结论
      return {
        ...state,
        drainSubmitting: false,
        drainPlan: null,
        fieldErrors: { ...state.fieldErrors, ...action.fieldErrors },
        drainFieldError: action.drainFieldError,
        drainGlobalError: action.message,
      };
    case 'drain/failed':
      // 腾容请求失败：清除旧方案、保留原判定，失败信息不得误作判定结论
      return {
        ...state,
        drainSubmitting: false,
        drainPlan: null,
        drainGlobalError: action.message,
      };
    default:
      return state;
  }
}
