import { useEffect, useState } from "react";

/**
 * 把 index.css 里的图表配色读成 JS 值。
 *
 * Recharts 的 stroke / fill 最终落成 SVG 呈现属性，而呈现属性不接受 CSS 的
 * var()，所以图表拿不到 CSS 变量，必须给它真实的 hex。为了不让 hex 出现两份，
 * 这里从 documentElement 的计算样式里读回来——CSS 仍是唯一的定义处。
 */

const ROLES = [
  "surface-1",
  "page",
  "text-primary",
  "text-secondary",
  "text-muted",
  "grid",
  "axis",
  "series-1",
  "delta-up",
  "delta-down",
] as const;

export type VizPalette = Record<(typeof ROLES)[number], string>;

function readPalette(): VizPalette {
  const styles = getComputedStyle(document.documentElement);
  return Object.fromEntries(
    ROLES.map((role) => [role, styles.getPropertyValue(`--${role}`).trim()]),
  ) as VizPalette;
}

/** 订阅配色，跟随系统深浅模式和 data-theme 切换。 */
export function useVizPalette(): VizPalette {
  const [palette, setPalette] = useState(readPalette);

  useEffect(() => {
    const refresh = () => setPalette(readPalette());

    // 系统深浅模式切换
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    media.addEventListener("change", refresh);

    // 用户手动切换（data-theme 变化）
    const observer = new MutationObserver(refresh);
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-theme"],
    });

    return () => {
      media.removeEventListener("change", refresh);
      observer.disconnect();
    };
  }, []);

  return palette;
}
