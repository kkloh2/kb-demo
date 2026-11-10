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

export const KnowledgeBaseIcon = () => (
  <svg {...base}>
    <path d="M4 5a2 2 0 0 1 2-2h13v15H6a2 2 0 0 0-2 2z" />
    <path d="M4 20a2 2 0 0 0 2 1h13v-3" />
    <path d="M9 7h6M9 11h4" />
  </svg>
);

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

export const PlusIcon = () => (
  <svg {...base}>
    <path d="M12 5v14M5 12h14" />
  </svg>
);

export const SearchIcon = () => (
  <svg {...base}>
    <circle cx="11" cy="11" r="7" />
    <path d="M20 20l-3.5-3.5" />
  </svg>
);

export const StarIcon = ({ filled = false }: { filled?: boolean }) => (
  <svg {...base} fill={filled ? "currentColor" : "none"}>
    <path d="M12 3.5l2.6 5.3 5.9.9-4.3 4.1 1 5.8-5.2-2.7-5.2 2.7 1-5.8-4.3-4.1 5.9-.9z" />
  </svg>
);

export const MoreIcon = () => (
  <svg {...base}>
    <circle cx="12" cy="5" r="1" fill="currentColor" />
    <circle cx="12" cy="12" r="1" fill="currentColor" />
    <circle cx="12" cy="19" r="1" fill="currentColor" />
  </svg>
);

export const ListIcon = () => (
  <svg {...base}>
    <path d="M9 6h11M9 12h11M9 18h11" />
    <circle cx="4.5" cy="6" r="0.8" fill="currentColor" />
    <circle cx="4.5" cy="12" r="0.8" fill="currentColor" />
    <circle cx="4.5" cy="18" r="0.8" fill="currentColor" />
  </svg>
);

export const GridIcon = () => (
  <svg {...base}>
    <rect x="4" y="4" width="16" height="16" rx="1.5" />
    <path d="M4 9.33h16M4 14.67h16M9.33 4v16M14.67 4v16" />
  </svg>
);

/** Sort arrows (down + up). Active direction is drawn solid, the other faded. */
export const SortIcon = ({ dir }: { dir: "asc" | "desc" | "none" }) => (
  <svg {...base}>
    <g opacity={dir === "asc" ? 0.35 : 1}>
      <path d="M8 4v15" />
      <path d="M5 16l3 3 3-3" />
    </g>
    <g opacity={dir === "desc" ? 0.35 : 1}>
      <path d="M16 20V5" />
      <path d="M13 8l3-3 3 3" />
    </g>
  </svg>
);

export const ChevronIcon = ({ dir }: { dir: "left" | "right" | "down" }) => (
  <svg {...base}>
    <path d={dir === "left" ? "M15 6l-6 6 6 6" : dir === "right" ? "M9 6l6 6-6 6" : "M6 9l6 6 6-6"} />
  </svg>
);

export const PageEdgeIcon = ({ dir }: { dir: "first" | "last" }) => (
  <svg {...base}>
    <path d={dir === "first" ? "M17 6l-6 6 6 6M7 6v12" : "M7 6l6 6-6 6M17 6v12"} />
  </svg>
);

export const SettingsIcon = () => (
  <svg {...base}>
    <circle cx="12" cy="12" r="3" />
    <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" />
  </svg>
);

export const CloseIcon = () => (
  <svg {...base}>
    <path d="M6 6l12 12M18 6L6 18" />
  </svg>
);

export const UploadIcon = () => (
  <svg {...base}>
    <path d="M12 16V4M7 9l5-5 5 5" />
    <path d="M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3" />
  </svg>
);

export const DownloadIcon = () => (
  <svg {...base}>
    <path d="M12 4v12M7 11l5 5 5-5" />
    <path d="M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3" />
  </svg>
);

export const FileIcon = () => (
  <svg {...base}>
    <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" />
    <path d="M14 3v5h5" />
  </svg>
);

export const CheckIcon = () => (
  <svg {...base}>
    <path d="M5 12.5l4.5 4.5L19 7.5" />
  </svg>
);
