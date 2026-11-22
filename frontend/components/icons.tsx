import type { SVGProps } from "react";

const PATHS: Record<string, string[]> = {
  dashboard: ["M3 3h7v7H3zM14 3h7v4h-7zM14 10h7v11h-7zM3 13h7v8H3z"],
  chat: ["M21 12a8 8 0 0 1-8 8H7l-4 3v-6.5A8 8 0 1 1 13 20"],
  tasks: ["M9 5h11M9 12h11M9 19h11", "M4 5l1.5 1.5L8 4M4 12l1.5 1.5L8 11M4 19l1.5 1.5L8 18"],
  studio: ["M4 5h16v11H4z", "M9.5 9.5v3l3-1.5z", "M8 20h8"],
  youtube: ["M21 8.5a3 3 0 0 0-2.1-2.1C17.2 6 12 6 12 6s-5.2 0-6.9.4A3 3 0 0 0 3 8.5C2.6 10.2 2.6 12 2.6 12s0 1.8.4 3.5a3 3 0 0 0 2.1 2.1C6.8 18 12 18 12 18s5.2 0 6.9-.4a3 3 0 0 0 2.1-2.1c.4-1.7.4-3.5.4-3.5s0-1.8-.4-3.5z", "M10.2 15V9l5 3z"],
  instagram: ["M7 3h10a4 4 0 0 1 4 4v10a4 4 0 0 1-4 4H7a4 4 0 0 1-4-4V7a4 4 0 0 1 4-4z", "M12 8.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7z", "M17.2 6.8h.01"],
  library: ["M4 4h5v16H4zM11 4h4v16h-4z", "M17.5 5.5l4 15-3.5 1-4-15z"],
  research: ["M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14z", "M20 20l-3.5-3.5"],
  calendar: ["M4 6h16v14H4z", "M8 3v4M16 3v4M4 10h16"],
  emails: ["M3 6h18v12H3z", "M3 7l9 6 9-6"],
  files: ["M4 4h6l2 3h8v13H4z"],
  memories: ["M12 4a4 4 0 0 1 4 4v1a3 3 0 0 1 0 6v1a4 4 0 0 1-8 0v-1a3 3 0 0 1 0-6V8a4 4 0 0 1 4-4z", "M9 9h6M9 14h6"],
  integrations: ["M10 4v5H6a2 2 0 0 0-2 2v3h4v6h4v-6h4v-6h4V9a2 2 0 0 0-2-2h-4V4z"],
  settings: ["M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6z", "M19 12a7 7 0 0 0-.1-1.2l2-1.5-2-3.4-2.3 1a7 7 0 0 0-2-1.2L14.2 3h-4l-.4 2.7a7 7 0 0 0-2 1.2l-2.3-1-2 3.4 2 1.5A7 7 0 0 0 5 12c0 .4 0 .8.1 1.2l-2 1.5 2 3.4 2.3-1a7 7 0 0 0 2 1.2l.4 2.7h4l.4-2.7a7 7 0 0 0 2-1.2l2.3 1 2-3.4-2-1.5c.1-.4.1-.8.1-1.2z"],
  permissions: ["M12 3l8 3v6c0 5-3.4 8-8 9-4.6-1-8-4-8-9V6z", "M9 12l2 2 4-4"],
  logs: ["M4 5h16v14H4z", "M8 9h8M8 13h8M8 17h4"],
  mobile: ["M8 3h8a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1H8a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z", "M11 18h2"],
  bell: ["M6 9a6 6 0 1 1 12 0c0 4 1.5 5.5 2 6H4c.5-.5 2-2 2-6z", "M10 19a2 2 0 0 0 4 0"],
  power: ["M12 3v8", "M6.3 6.3a8 8 0 1 0 11.4 0"],
  menu: ["M4 7h16M4 12h16M4 17h16"],
  plus: ["M12 5v14M5 12h14"],
  mic: ["M12 3a3 3 0 0 1 3 3v5a3 3 0 0 1-6 0V6a3 3 0 0 1 3-3z", "M5 11a7 7 0 0 0 14 0M12 18v3"],
  send: ["M4 12l16-8-6 16-3-6z"],
  play: ["M7 4l13 8-13 8z"],
  download: ["M12 4v11", "M7 11l5 5 5-5", "M5 20h14"],
  external: ["M14 4h6v6", "M20 4l-9 9", "M19 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h5"],
  check: ["M4 12.5l5 5L20 6"],
  x: ["M6 6l12 12M18 6L6 18"],
  refresh: ["M20 11a8 8 0 1 0-2.3 5.7", "M20 4v7h-7"],
  search: ["M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14z", "M20 20l-3.5-3.5"],
  folder: ["M4 6h6l2 3h8v10H4z"],
  trash: ["M4 7h16", "M9 7V4h6v3", "M6 7l1 13h10l1-13"],
  edit: ["M4 20h4L20 8l-4-4L4 16z"],
  clock: ["M12 4a8 8 0 1 0 0 16 8 8 0 0 0 0-16z", "M12 8v5l3 2"],
  shield: ["M12 3l8 3v6c0 5-3.4 8-8 9-4.6-1-8-4-8-9V6z"],
  spark: ["M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"],
  film: ["M3 5h18v14H3z", "M7 5v14M17 5v14M3 12h18"],
  arrow: ["M5 12h14", "M13 6l6 6-6 6"],
  logout: ["M15 4h4a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1h-4", "M10 8l-4 4 4 4M6 12h10"],
};

export type IconName = keyof typeof PATHS;

export function Icon({
  name,
  className = "h-4 w-4",
  ...rest
}: { name: IconName | string; className?: string } & SVGProps<SVGSVGElement>) {
  const paths = PATHS[name] ?? PATHS.spark;
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round" {...rest}>
      {paths.map((path, index) => (
        <path key={index} d={path} />
      ))}
    </svg>
  );
}
