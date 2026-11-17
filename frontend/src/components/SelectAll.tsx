import { useEffect, useRef } from "react";

interface Props {
  selected: number; // how many of the rows below are selected
  total: number; // how many can be selected
  onChange: (all: boolean) => void;
  label: string;
}

/** A table header checkbox: ticked when every selectable row is, partly ticked when some are. */
export function SelectAll({ selected, total, onChange, label }: Props) {
  const ref = useRef<HTMLInputElement>(null);
  const all = total > 0 && selected === total;
  useEffect(() => {
    if (ref.current) ref.current.indeterminate = selected > 0 && !all;
  }, [selected, all]);
  return (
    <input ref={ref} type="checkbox" className="row-check" aria-label={label} checked={all} disabled={total === 0}
      onChange={() => onChange(!all)} />
  );
}
