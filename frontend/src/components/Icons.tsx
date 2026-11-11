import type { SVGProps } from "react";

const base: SVGProps<SVGSVGElement> = {
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.8,
  strokeLinecap: "round",
  strokeLinejoin: "round",
  "aria-hidden": true,
};

export const SignOutIcon = () => (
  <svg {...base}>
    <path d="M15 4h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3" />
    <path d="M10 17l-5-5 5-5" />
    <path d="M5 12h11" />
  </svg>
);

/** Panel outline with a chevron: points left to collapse, right to expand. */
export const PanelIcon = ({ expand = false }: { expand?: boolean }) => (
  <svg {...base}>
    <rect x="3" y="4" width="18" height="16" rx="2" />
    <path d="M9 4v16" />
    <path d={expand ? "M13.5 10l2 2-2 2" : "M15.5 10l-2 2 2 2"} />
  </svg>
);

