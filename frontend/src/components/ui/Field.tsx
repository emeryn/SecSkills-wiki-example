import { forwardRef, useId, type InputHTMLAttributes, type SelectHTMLAttributes } from "react";

const CONTROL =
  "h-9 w-full rounded-md border border-border bg-surface px-3 text-sm text-text placeholder:text-text-muted disabled:opacity-60 aria-invalid:border-danger";

interface FieldProps {
  label: string;
  error?: string;
  hint?: string;
  required?: boolean;
}

function FieldFrame({
  id,
  label,
  error,
  hint,
  required,
  children,
}: FieldProps & { id: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <label htmlFor={id} className="block font-medium">
        {label}
        {required === true && (
          <span aria-hidden className="ml-0.5 text-danger">
            *
          </span>
        )}
      </label>
      {children}
      {hint !== undefined && error === undefined && (
        <p id={`${id}-hint`} className="text-xs text-text-muted">
          {hint}
        </p>
      )}
      {error !== undefined && (
        <p id={`${id}-error`} role="alert" className="text-xs text-danger">
          {error}
        </p>
      )}
    </div>
  );
}

type TextFieldProps = FieldProps & InputHTMLAttributes<HTMLInputElement>;

/** Label above the input, inline error announced to assistive technology. */
export const TextField = forwardRef<HTMLInputElement, TextFieldProps>(function TextField(
  { label, error, hint, required, className = "", ...rest },
  ref,
) {
  const id = useId();
  return (
    <FieldFrame id={id} label={label} error={error} hint={hint} required={required}>
      <input
        ref={ref}
        id={id}
        required={required}
        aria-invalid={error !== undefined || undefined}
        aria-describedby={
          error !== undefined ? `${id}-error` : hint !== undefined ? `${id}-hint` : undefined
        }
        className={`${CONTROL} ${className}`}
        {...rest}
      />
    </FieldFrame>
  );
});

type SelectFieldProps = FieldProps &
  SelectHTMLAttributes<HTMLSelectElement> & { options: { value: string; label: string }[] };

export const SelectField = forwardRef<HTMLSelectElement, SelectFieldProps>(function SelectField(
  { label, error, hint, required, options, className = "", ...rest },
  ref,
) {
  const id = useId();
  return (
    <FieldFrame id={id} label={label} error={error} hint={hint} required={required}>
      <select
        ref={ref}
        id={id}
        aria-invalid={error !== undefined || undefined}
        className={`${CONTROL} ${className}`}
        {...rest}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </FieldFrame>
  );
});
