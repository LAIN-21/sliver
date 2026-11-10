type IconName =
  | "arrow"
  | "search"
  | "layers"
  | "code"
  | "pulse"
  | "pause"
  | "play"
  | "check"
  | "copy";

const paths: Record<IconName, string> = {
  arrow: "M5 12h14M13 6l6 6-6 6",
  search: "M21 21l-5-5M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0",
  layers: "m3 7 9-4 9 4-9 4-9-4Zm0 5 9 4 9-4M3 17l9 4 9-4",
  code: "m8 5-6 7 6 7m8-14 6 7-6 7m-3-16-2 18",
  pulse: "M2 12h5l3-8 4 16 3-8h5",
  pause: "M8 5v14M16 5v14",
  play: "m8 4 12 8-12 8V4Z",
  check: "m5 12 4 4L19 6",
  copy: "M8 8H4v13h13v-4M8 3h13v14H8V3Z",
};

export function ExchangeIcon({
  name,
  size = 20,
}: {
  name: IconName;
  size?: number;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={paths[name]} />
    </svg>
  );
}

export function SliverMark() {
  return (
    <svg
      width="30"
      height="33"
      viewBox="0 0 30 33"
      fill="none"
      aria-hidden="true"
    >
      <path
        d="m2 13 7-4v20l-7 4V13Zm10-7 7-4v24l-7 4V6Zm10-4 6-2v21l-6 3V2Z"
        fill="currentColor"
      />
    </svg>
  );
}
