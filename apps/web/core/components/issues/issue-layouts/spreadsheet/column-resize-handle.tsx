/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import type { MouseEvent } from "react";

type Props = {
  onResizeStart: (event: MouseEvent<HTMLElement>) => void;
  onReset: () => void;
};

/** Drag handle on the right edge of a header cell. Parent `th` must be positioned. */
export function ColumnResizeHandle({ onResizeStart, onReset }: Props) {
  return (
    <div
      role="separator"
      aria-orientation="vertical"
      title="Drag to resize, double-click to reset"
      className="absolute top-0 right-0 z-[1] h-full w-2 cursor-col-resize select-none hover:bg-accent-primary/50 active:bg-accent-primary"
      onMouseDown={onResizeStart}
      onDoubleClick={onReset}
    />
  );
}
