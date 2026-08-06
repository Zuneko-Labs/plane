/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// plane imports
import { SearchIcon, CloseIcon } from "@plane/propel/icons";

type Props = {
  searchQuery: string;
  updateSearchQuery: (val: string) => void;
  placeholder?: string;
};

export function WorkItemNameSearchInput(props: Props) {
  const { searchQuery, updateSearchQuery, placeholder = "Search work items" } = props;

  const handleInputKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Escape" && searchQuery.trim() !== "") updateSearchQuery("");
  };

  return (
    <div className="flex w-52 flex-shrink-0 items-center justify-start gap-2 rounded-md border border-subtle px-2.5 py-1.5 text-placeholder">
      <SearchIcon className="h-3.5 w-3.5 flex-shrink-0" />
      <input
        className="w-full border-none bg-transparent text-13 text-primary placeholder:text-placeholder focus:outline-none"
        placeholder={placeholder}
        value={searchQuery}
        onChange={(e) => updateSearchQuery(e.target.value)}
        onKeyDown={handleInputKeyDown}
      />
      {searchQuery.trim() !== "" && (
        <button type="button" className="grid flex-shrink-0 place-items-center" onClick={() => updateSearchQuery("")}>
          <CloseIcon className="h-3 w-3" />
        </button>
      )}
    </div>
  );
}
