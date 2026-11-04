"use client";

import { useState, useEffect } from "react";
import { ChevronDown, Search } from "lucide-react";
import { cn } from "@/lib/utils";

interface SearchBarProps {
  onSearch: (query: string, filter: SearchFilter) => void;
  sort: ShelfSort;
  onSortChange: (sort: ShelfSort) => void;
  className?: string;
}

export type SearchFilter = "all" | "artist" | "album" | "lyricist" | "genre";
export type ShelfSort = "newest" | "album" | "artist";

const filters: { value: SearchFilter; label: string }[] = [
  { value: "all", label: "All fields" },
  { value: "artist", label: "Artist" },
  { value: "album", label: "Album" },
  { value: "lyricist", label: "Lyricist" },
  { value: "genre", label: "Genre" },
];

const sorts: { value: ShelfSort; label: string }[] = [
  { value: "newest", label: "Newest first" },
  { value: "album", label: "Album A–Z" },
  { value: "artist", label: "Artist A–Z" },
];

export function SearchBar({ onSearch, sort, onSortChange, className }: SearchBarProps) {
  const [query, setQuery] = useState("");
  const [activeFilter, setActiveFilter] = useState<SearchFilter>("all");
  const [debouncedQuery, setDebouncedQuery] = useState("");

  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedQuery(query);
    }, 300);

    return () => clearTimeout(timer);
  }, [query]);

  useEffect(() => {
    onSearch(debouncedQuery, activeFilter);
  }, [debouncedQuery, activeFilter, onSearch]);

  return (
    <div className={cn("space-y-3", className)}>
      <div className="relative">
        <Search className="pointer-events-none absolute left-4 top-1/2 h-5 w-5 -translate-y-1/2 text-muted-foreground" />
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search album, artist, lyricist..."
          aria-label="Search the collection"
          className="h-12 w-full rounded-full border border-border bg-card pl-11 pr-4 text-base text-foreground shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        />
      </div>

      <div className="flex flex-wrap gap-2">
        <PillSelect
          label="Search field"
          value={activeFilter}
          onChange={(value) => setActiveFilter(value as SearchFilter)}
          options={filters}
        />
        <PillSelect
          label="Sort"
          value={sort}
          onChange={(value) => onSortChange(value as ShelfSort)}
          options={sorts}
        />
      </div>
    </div>
  );
}

function PillSelect({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <div className="relative">
      <select
        aria-label={label}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="h-10 appearance-none rounded-full border border-border bg-card pl-4 pr-9 text-sm text-foreground shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      <ChevronDown className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
    </div>
  );
}
