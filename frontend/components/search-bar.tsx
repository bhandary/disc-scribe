"use client";

import { useState, useEffect } from "react";
import { Search } from "lucide-react";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

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
  artist: "Search by artist (e.g. A. R. Rahman)...",
  album: "Search by album name...",
  lyricist: "Search by lyricist...",
  genre: "Search by genre (e.g. Hindi Film)...",
};

export function SearchBar({ onSearch, className }: SearchBarProps) {
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
            onClick={() => setActiveFilter(filter.value)}
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
    </div>
  );
}
