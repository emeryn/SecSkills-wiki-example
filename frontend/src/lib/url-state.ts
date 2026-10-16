import { useCallback, useMemo } from "react";
import { useSearchParams } from "react-router";

/**
 * List view state (search, filters, sort, page) kept in the query string, so the back button and
 * shared links restore the exact view. Unknown values fall back to the defaults.
 */
export function useUrlState<T extends Record<string, string>>(
  defaults: T,
  allowed: Partial<Record<keyof T, readonly string[]>> = {},
) {
  const [params, setParams] = useSearchParams();

  const state = useMemo(() => {
    const result = { ...defaults };
    for (const key of Object.keys(defaults) as (keyof T & string)[]) {
      const value = params.get(key);
      const options = allowed[key];
      if (value !== null && (options === undefined || options.includes(value))) {
        result[key] = value as T[typeof key];
      }
    }
    return result;
  }, [params, defaults, allowed]);

  const update = useCallback(
    (changes: Partial<T>, { resetPage = true }: { resetPage?: boolean } = {}) => {
      setParams(
        (current) => {
          const next = new URLSearchParams(current);
          for (const [key, value] of Object.entries(changes) as [string, string | undefined][]) {
            if (value === undefined || value === "" || value === defaults[key]) next.delete(key);
            else next.set(key, value);
          }
          if (resetPage && !("page" in changes)) next.delete("page");
          return next;
        },
        { replace: true },
      );
    },
    [setParams, defaults],
  );

  return [state, update] as const;
}
