import type { CSSProperties } from "react";
import "./SliverScene.css";

/** A lightweight schematic; no graphics runtime is needed to understand the product. */
export default function SliverIllustration() {
  return (
    <div className="sliver-scene" data-renderer="fallback" aria-hidden="true">
      <div className="sliver-scene__fallback">
        {Array.from({ length: 9 }, (_, index) => (
          <span
            key={index}
            className={`sliver-scene__plate${index === 6 ? " sliver-scene__plate--selected" : ""}`}
            style={{ "--plate-index": index } as CSSProperties}
          >
            <i />
            <i />
            <i />
            <i />
            <i />
            <i />
          </span>
        ))}
      </div>
    </div>
  );
}
