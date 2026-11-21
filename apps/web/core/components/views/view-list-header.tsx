/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import React, { useEffect, useRef, useState } from "react";
import { observer } from "mobx-react";
// icons
import { ListFilter } from "lucide-react";
import { useOutsideClickDetector } from "@plane/hooks";
import { SearchIcon, CloseIcon } from "@plane/propel/icons";
// hooks
import { useMember } from "@/hooks/store/use-member";
import { useProjectView } from "@/hooks/store/use-project-view";
import { FiltersDropdown } from "../issues/issue-layouts/filters";
import { ViewFiltersSelection } from "./filters/filter-selection";
import { ViewOrderByDropdown } from "./filters/order-by";
import { IconButton } from "@plane/propel/icon-button";

export const ViewListHeader = observer(function ViewListHeader() {
  // states
  const [isSearchOpen, setIsSearchOpen] = useState(false);
  // refs
  const inputRef = useRef<HTMLInputElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // store hooks
  const { filters, updateFilters } = useProjectView();
  const {
    project: { projectMemberIds },
  } = useMember();

  const storeQuery = filters?.searchQuery ?? "";
  // local value keeps typing instant; store (and the filtered list) updates debounced
  const [inputValue, setInputValue] = useState(storeQuery);

  // handlers
  const handleInputChange = (value: string) => {
    setInputValue(value);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => updateFilters("searchQuery", value), 200);
  };

  const clearSearch = () => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    setInputValue("");
    updateFilters("searchQuery", "");
  };

  const handleInputKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Escape") {
      if (inputValue.trim() !== "") {
        clearSearch();
      } else {
        setIsSearchOpen(false);
        inputRef.current?.blur();
      }
    }
  };

  // outside click detector hook
  useOutsideClickDetector(containerRef, () => {
    if (isSearchOpen && inputValue.trim() === "") setIsSearchOpen(false);
  });

  // external changes to the store query (e.g. clear all filters) -> sync local value
  useEffect(() => {
    setInputValue((prev) => (prev === storeQuery ? prev : storeQuery));
    if (storeQuery.trim() !== "") setIsSearchOpen(true);
  }, [storeQuery]);

  // focus once the input is actually mounted
  useEffect(() => {
    if (isSearchOpen) inputRef.current?.focus();
  }, [isSearchOpen]);

  // flush pending debounce on unmount
  useEffect(
    () => () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    },
    []
  );

  return (
    <div className="flex h-full items-center gap-2">
      <div ref={containerRef} className="flex items-center">
        {!isSearchOpen ? (
          <IconButton variant="ghost" size="lg" onClick={() => setIsSearchOpen(true)} icon={SearchIcon} />
        ) : (
          <div className="flex w-64 shrink-0 items-center gap-1.5 rounded-md border border-subtle bg-surface-1 px-2.5 py-1.5 text-placeholder">
            <SearchIcon className="h-3.5 w-3.5 shrink-0" />
            <input
              ref={inputRef}
              className="min-w-0 flex-1 border-none bg-transparent text-13 text-primary placeholder:text-placeholder focus:outline-none"
              placeholder="Search"
              value={inputValue}
              onChange={(e) => handleInputChange(e.target.value)}
              onKeyDown={handleInputKeyDown}
            />
            <button
              type="button"
              className="grid shrink-0 place-items-center"
              onClick={() => {
                clearSearch();
                setIsSearchOpen(false);
              }}
            >
              <CloseIcon className="h-3 w-3" />
            </button>
          </div>
        )}
      </div>
      <div className="hidden items-center gap-2 md:flex">
        <ViewOrderByDropdown
          sortBy={filters.sortBy}
          sortKey={filters.sortKey}
          onChange={(val) => {
            if (val.key) updateFilters("sortKey", val.key);
            if (val.order) updateFilters("sortBy", val.order);
          }}
        />
        <FiltersDropdown
          icon={<ListFilter className="h-3 w-3" />}
          title="Filters"
          placement="bottom-end"
          isFiltersApplied={false}
        >
          <ViewFiltersSelection
            filters={filters}
            handleFiltersUpdate={updateFilters}
            memberIds={projectMemberIds ?? undefined}
          />
        </FiltersDropdown>
      </div>
    </div>
  );
});
