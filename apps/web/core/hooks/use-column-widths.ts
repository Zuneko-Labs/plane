/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { CSSProperties, MouseEvent as ReactMouseEvent } from "react";
import { useCallback, useMemo, useRef, useState } from "react";
import { getValueFromLocalStorage, setValueIntoLocalStorage } from "./use-local-storage";

export const MIN_COLUMN_WIDTH = 80;
const MAX_COLUMN_WIDTH = 1200;

const clamp = (value: number) => Math.min(MAX_COLUMN_WIDTH, Math.max(MIN_COLUMN_WIDTH, Math.round(value)));

const cssVarName = (key: string) => `--col-${key}`;

/**
 * Cell style driven by a CSS variable set on the table, so resizing a column
 * never re-renders the rows. Falls back to `fallbackPx` until the user resizes.
 */
export const getColumnStyle = (key: string, fallbackPx: number): CSSProperties => {
  const value = `var(${cssVarName(key)}, ${fallbackPx}px)`;
  return { width: value, minWidth: value, maxWidth: value };
};

/**
 * Excel-like column widths. Persisted per `storageKey` in localStorage.
 */
export const useColumnWidths = (storageKey: string) => {
  const [widths, setWidths] = useState<Record<string, number>>(() => getValueFromLocalStorage(storageKey, {}));
  const widthsRef = useRef(widths);
  widthsRef.current = widths;

  const commit = useCallback(
    (next: Record<string, number>) => {
      widthsRef.current = next;
      setWidths(next);
      setValueIntoLocalStorage(storageKey, next);
    },
    [storageKey]
  );

  const startResize = useCallback(
    (key: string, event: ReactMouseEvent<HTMLElement>) => {
      if (event.button !== 0) return;
      event.preventDefault();
      event.stopPropagation();
      const cell = event.currentTarget.parentElement;
      if (!cell) return;
      const startX = event.clientX;
      const startWidth = cell.getBoundingClientRect().width;
      const previousCursor = document.body.style.cursor;
      const previousUserSelect = document.body.style.userSelect;
      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";

      // resize only while the mouse button is held down
      const finish = () => {
        window.removeEventListener("mousemove", onMove);
        window.removeEventListener("mouseup", finish);
        window.removeEventListener("blur", finish);
        document.body.style.cursor = previousCursor;
        document.body.style.userSelect = previousUserSelect;
        setValueIntoLocalStorage(storageKey, widthsRef.current);
      };
      function onMove(e: MouseEvent) {
        // button released outside the window / missed mouseup: stop, don't follow the hover
        if (e.buttons === 0) {
          finish();
          return;
        }
        // live update without persisting on every move
        const next = { ...widthsRef.current, [key]: clamp(startWidth + e.clientX - startX) };
        widthsRef.current = next;
        setWidths(next);
      }
      window.addEventListener("mousemove", onMove);
      window.addEventListener("mouseup", finish);
      window.addEventListener("blur", finish);
    },
    [storageKey]
  );

  const resetWidth = useCallback(
    (key: string) => {
      const next = { ...widthsRef.current };
      delete next[key];
      commit(next);
    },
    [commit]
  );

  const cssVars = useMemo(() => {
    const vars: Record<string, string> = {};
    Object.entries(widths).forEach(([key, value]) => {
      if (typeof value === "number") vars[cssVarName(key)] = `${value}px`;
    });
    return vars as CSSProperties;
  }, [widths]);

  return { cssVars, startResize, resetWidth };
};
