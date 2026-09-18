import type { FormEvent } from 'react';
import type { RobustFieldKey, RobustPlanResponse } from '../lib/api';
import { ROBUST_FIELDS } from '../lib/api';
import { buildRobustPlanView } from '../lib/view';

interface RobustPlanPanelProps {
  /** 当前方案（无则只展示入口表单） */
  plan: RobustPlanResponse | null;
  /** Q/U/E 的输入值与变更回调 */
  values: Record<RobustFieldKey, string>;
  onValueChange: (field: RobustFieldKey, value: string) => void;
  /** Q/U/E 的字段级错误（非法参数定位） */
  fieldErrors: Partial<Record<string, string>>;
  /** 稳健方案请求级错误 */
  globalError: string | null;
  submitting: boolean;
  onSubmit: () => void;
}

const FIELD_META: Record<RobustFieldKey, { label: string; unit: string }> = {
  Q: { label: '单刻度量 Q', unit: 'mL' },
  U: { label: '糖度波动 U', unit: '%' },
  E: { label: '终态容差 E', unit: '%' },
};

/** 稳健刻度方案面板：仅挂在「允许补加」结论之下，填写 Q/U/E 后生成方案。 */
export function RobustPlanPanel({
  plan,
  values,
  onValueChange,
  fieldErrors,
  globalError,
  submitting,
  onSubmit,
}: RobustPlanPanelProps) {
  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onSubmit();
  }

  const view = plan ? buildRobustPlanView(plan) : null;
  const robust = view?.status === 'ROBUST';

  return (
    <section className="robust" data-testid="robust-panel" aria-label="稳健刻度方案">
      <h2 className="robust-title">稳健刻度方案</h2>
      <p className="robust-intro">
        按固定刻度 nQ 投料，对糖浆实际糖度区间 [S-U, S+U] 两端点计算终态糖度，
        取最坏偏差最小的刻度（同值取较小刻度）。
      </p>
      <form onSubmit={handleSubmit} noValidate className="robust-form">
        {ROBUST_FIELDS.map((field) => {
          const error = fieldErrors[field];
          return (
            <div className="field" key={field}>
              <label htmlFor={`field-${field}`}>
                {FIELD_META[field].label}（{FIELD_META[field].unit}）
              </label>
              <input
                id={`field-${field}`}
                name={field}
                inputMode="decimal"
                autoComplete="off"
                placeholder="最多四位小数"
                value={values[field]}
                onChange={(e) => onValueChange(field, e.target.value)}
                aria-invalid={Boolean(error)}
                aria-describedby={error ? `error-${field}` : undefined}
              />
              {error && (
                <p
                  className="field-error"
                  id={`error-${field}`}
                  role="alert"
                  data-testid={`error-${field}`}
                >
                  {error}
                </p>
              )}
            </div>
          );
        })}
        <button type="submit" disabled={submitting} data-testid="robust-entry">
          {submitting ? '生成中…' : '生成稳健刻度方案'}
        </button>
      </form>
      {globalError && (
        <div className="global-error" role="alert" data-testid="robust-error">
          {globalError}
        </div>
      )}
      {view && (
        <div
          className={`robust-result ${robust ? 'robust-ok' : 'robust-blocked'}`}
          data-testid="robust-result"
          aria-live="polite"
        >
          <div data-testid="robust-status" className="verdict">
            {view.statusText}
          </div>
          <dl className="rows">
            {view.rows.map((row) => (
              <div key={row.testId} className="row">
                <dt>{row.label}</dt>
                <dd data-testid={row.testId}>{row.value}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}
    </section>
  );
}
