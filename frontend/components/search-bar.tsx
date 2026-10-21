"use client";

import { useState, useEffect, useRef } from "react";
import { Search } from "lucide-react";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api";

interface SearchBarProps {
  onSearch: (query: string, filter: SearchFilter) => void;
  className?: string;
}

export type SearchFilter = "all" | "artist" | "album" | "lyricist" | "genre";

const filters: { value: SearchFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "artist", label: "Artist" },
  { value: "album", label: "Album" },
  { value: "lyricist", label: "Lyricist" },
  { value: "genre", label: "Genre" },
];

const PLACEHOLDERS: Record<SearchFilter, string> = {
  all: "Search your collection...",
  artist: "Search or pick an artist...",
  album: "Search or pick an album...",
  lyricist: "Search or pick a lyricist...",
  genre: "Search or pick a genre...",
};

export function SearchBar({ onSearch, className }: SearchBarProps) {
  const [query, setQuery] = useState("");
  const [activeFilter, setActiveFilter] = useState<SearchFilter>("all");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [facets, setFacets] = useState<Array<{ value: string; count: number }>>([]);
  const [isLoadingFacets, setIsLoadingFacets] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedQuery(query);
    }, 300);

    return () => clearTimeout(timer);
  }, [query]);

  const onSearchRef = useRef(onSearch);
  onSearchRef.current = onSearch;

  useEffect(() => {
    onSearchRef.current(debouncedQuery, activeFilter);
  }, [debouncedQuery, activeFilter]);

  useEffect(() => {
    if (activeFilter === "all") {
      setFacets([]);
      return;
    }

    let cancelled = false;
    setIsLoadingFacets(true);
    api
      .getFacets(activeFilter)
      .then((data) => {
        if (!cancelled) setFacets(data.values);
      })
      .catch((error) => {
        console.error("Failed to load filters:", error);
        if (!cancelled) setFacets([]);
      })
      .finally(() => {
        if (!cancelled) setIsLoadingFacets(false);
      });

    return () => {
      cancelled = true;
    };
  }, [activeFilter]);

  const selectFilter = (filter: SearchFilter) => {
    setActiveFilter(filter);
    if (filter === "all") {
      return;
    }
    // Switching fields should start from the full value list, not a leftover query.
    setQuery("");
    setDebouncedQuery("");
  };

  const visibleFacets = query
    ? facets.filter((facet) =>
        facet.value.toLowerCase().includes(query.toLowerCase())
      )
    : facets;

  return (
    <div className={cn("space-y-3", className)}>
      {/* Search input */}
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-muted-foreground" />
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={PLACEHOLDERS[activeFilter]}
          className="pl-10 h-12 text-base glass border-white/20 focus:border-vinyl-gold"
        />
      </div>
      
      {/* Filter pills */}
      <div className="flex gap-2 flex-wrap">
        {filters.map((filter) => (
          <button
            key={filter.value}
            type="button"
            onClick={() => selectFilter(filter.value)}
            className={cn(
              "px-4 py-1.5 rounded-full text-sm font-medium transition-all",
              activeFilter === filter.value
                ? "bg-vinyl-gold text-vinyl-obsidian shadow-lg shadow-amber-900/30"
                : "bg-white/5 text-foreground hover:bg-white/10 border border-white/10"
            )}
          >
            {filter.label}
          </button>
        ))}
      </div>

      {activeFilter !== "all" && (
        <div className="max-h-40 overflow-y-auto rounded-lg border border-white/10 bg-white/5 p-2">
          {isLoadingFacets ? (
            <p className="px-2 py-1 text-xs text-muted-foreground">Loading {activeFilter}s…</p>
          ) : visibleFacets.length === 0 ? (
            <p className="px-2 py-1 text-xs text-muted-foreground">No matching {activeFilter}s</p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {visibleFacets.map((facet) => (
                <button
                  key={facet.value}
                  type="button"
                  onClick={() => {
                    setQuery(facet.value);
                    setDebouncedQuery(facet.value);
                  }}
                  className={cn(
                    "px-3 py-1 rounded-full text-xs transition-all border",
                    query === facet.value
                      ? "bg-vinyl-gold text-vinyl-obsidian border-transparent"
                      : "bg-black/20 text-foreground border-white/10 hover:bg-white/10"
                  )}
                >
                  {facet.value}
                  <span className="ml-1 opacity-70">{facet.count}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
