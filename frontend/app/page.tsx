"use client";

import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import { Loader2, MoreHorizontal, Upload } from "lucide-react";
import { CDJewelCase, CDSpine } from "@/components/cd-jewel-case";
import { SearchBar, SearchFilter, ShelfSort } from "@/components/search-bar";
import { DigitalBookletDrawer } from "@/components/digital-booklet-drawer";
import { CSVUploadModal } from "@/components/csv-upload-modal";
import { SettingsModal } from "@/components/settings-modal";
import { Button } from "@/components/ui/button";
import { api, CD } from "@/lib/api";

export default function Home() {
  const [cds, setCDs] = useState<CD[]>([]);
  const [selectedCD, setSelectedCD] = useState<CD | null>(null);
  const [isDrawerOpen, setIsDrawerOpen] = useState(false);
  const [isUploadModalOpen, setIsUploadModalOpen] = useState(false);
  const [isSettingsModalOpen, setIsSettingsModalOpen] = useState(false);
  const [isMenuOpen, setIsMenuOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchFilter, setSearchFilter] = useState<SearchFilter>("all");
  const [sort, setSort] = useState<ShelfSort>("newest");
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const menuRef = useRef<HTMLDivElement>(null);

  const loadCDs = useCallback(async () => {
    setIsLoading(true);
    try {
      const params: Record<string, string | number> = { page, limit: 20 };

      if (searchQuery) {
        if (searchFilter === "all") {
          params.q = searchQuery;
        } else {
          params[searchFilter === "album" ? "album_name" : searchFilter] = searchQuery;
        }
      }

      const response = await api.searchCDs(params);
      setCDs(response.cds);
      setTotal(response.total);
    } catch (error) {
      console.error("Failed to load CDs:", error);
    } finally {
      setIsLoading(false);
    }
  }, [searchQuery, searchFilter, page]);

  useEffect(() => {
    loadCDs();
  }, [loadCDs]);

  useEffect(() => {
    if (!isMenuOpen) return;
    const onPointerDown = (event: MouseEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) setIsMenuOpen(false);
    };
    document.addEventListener("mousedown", onPointerDown);
    return () => document.removeEventListener("mousedown", onPointerDown);
  }, [isMenuOpen]);

  const handleSearch = useCallback((query: string, filter: SearchFilter) => {
    setSearchQuery(query);
    setSearchFilter(filter);
    setPage(1);
  }, []);

  const handleCDClick = (cd: CD) => {
    setSelectedCD(cd);
    setIsDrawerOpen(true);
  };

  const shelf = useMemo(() => {
    const copy = [...cds];
    copy.sort((a, b) => {
      if (sort === "album") return a.album_name.localeCompare(b.album_name);
      if (sort === "artist") {
        return a.artist.localeCompare(b.artist) || a.album_name.localeCompare(b.album_name);
      }
      return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
    });
    return copy;
  }, [cds, sort]);

  const recent = useMemo(() => {
    return [...cds]
      .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
      .slice(0, 8);
  }, [cds]);

  const artistCount = new Set(cds.map((cd) => cd.artist.toLowerCase())).size;
  const genreCount = new Set(cds.map((cd) => cd.genre.toLowerCase())).size;
  const collectionComplete = total > 0 && total === cds.length;
  const subtitle = collectionComplete
    ? `${total} ${total === 1 ? "album" : "albums"} · ${artistCount} ${artistCount === 1 ? "artist" : "artists"} · ${genreCount} ${genreCount === 1 ? "genre" : "genres"}`
    : `${total} ${total === 1 ? "album" : "albums"}`;

  return (
    <div className="min-h-screen bg-background">
      <main className="mx-auto w-full max-w-lg px-5 py-8 sm:px-6 sm:py-12">
        <header className="flex items-start justify-between gap-4">
          <div>
            <h1 className="font-serif text-5xl font-medium tracking-tight text-foreground">
              DiscVault
            </h1>
            <p className="mt-2 text-sm text-muted-foreground">{subtitle}</p>
          </div>
          <div className="relative" ref={menuRef}>
            <button
              type="button"
              aria-label="Collection menu"
              aria-expanded={isMenuOpen}
              onClick={() => setIsMenuOpen((open) => !open)}
              className="flex h-10 w-10 items-center justify-center rounded-full border border-border bg-card text-foreground shadow-sm hover:bg-accent"
            >
              <MoreHorizontal className="h-5 w-5" />
            </button>
            {isMenuOpen && (
              <div className="absolute right-0 z-20 mt-2 w-48 rounded-2xl border border-border bg-card p-1 shadow-card">
                <button
                  type="button"
                  className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-sm hover:bg-accent"
                  onClick={() => {
                    setIsMenuOpen(false);
                    setIsUploadModalOpen(true);
                  }}
                >
                  <Upload className="h-4 w-4" />
                  Import CSV
                </button>
                <button
                  type="button"
                  className="flex w-full rounded-xl px-3 py-2 text-left text-sm hover:bg-accent"
                  onClick={() => {
                    setIsMenuOpen(false);
                    setIsSettingsModalOpen(true);
                  }}
                >
                  API settings
                </button>
              </div>
            )}
          </div>
        </header>

        {!searchQuery && recent.length > 0 && (
          <section className="mt-10">
            <h2 className="text-[11px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
              Recently shelved
            </h2>
            <div className="mt-4 flex gap-2 overflow-x-auto pb-1">
              {recent.map((cd) => (
                <CDSpine key={cd.id} cd={cd} onClick={() => handleCDClick(cd)} />
              ))}
            </div>
          </section>
        )}

        <div className="mt-8">
          <SearchBar onSearch={handleSearch} sort={sort} onSortChange={setSort} />
        </div>

        <div className="mt-3 flex h-5 items-center text-xs text-muted-foreground">
          {isLoading && (
            <span className="inline-flex items-center gap-2">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              Loading
            </span>
          )}
        </div>

        {shelf.length === 0 && !isLoading ? (
          <div className="py-16 text-center">
            <h2 className="font-serif text-2xl text-foreground">
              {searchQuery ? "No albums match" : "Nothing on the shelf"}
            </h2>
            <p className="mx-auto mt-2 max-w-xs text-sm text-muted-foreground">
              {searchQuery
                ? "Try a different album, artist, or lyricist."
                : "Import a CSV to start the collection."}
            </p>
            {!searchQuery && (
              <Button className="mt-6" onClick={() => setIsUploadModalOpen(true)}>
                <Upload className="h-4 w-4" />
                Import CSV
              </Button>
            )}
          </div>
        ) : (
          <ul className="mt-2 space-y-3">
            {shelf.map((cd) => (
              <li key={cd.id}>
                <CDJewelCase cd={cd} onClick={() => handleCDClick(cd)} />
              </li>
            ))}
          </ul>
        )}

        {total > 20 && (
          <div className="mt-8 flex items-center justify-center gap-3">
            <Button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page === 1}
              variant="secondary"
              size="sm"
            >
              Previous
            </Button>
            <span className="text-sm text-muted-foreground">
              Page {page} of {Math.ceil(total / 20)}
            </span>
            <Button
              onClick={() => setPage((p) => p + 1)}
              disabled={page >= Math.ceil(total / 20)}
              variant="secondary"
              size="sm"
            >
              Next
            </Button>
          </div>
        )}
      </main>

      <DigitalBookletDrawer
        cd={selectedCD}
        isOpen={isDrawerOpen}
        onClose={() => setIsDrawerOpen(false)}
      />
      <CSVUploadModal
        isOpen={isUploadModalOpen}
        onClose={() => setIsUploadModalOpen(false)}
        onUploadComplete={loadCDs}
      />
      <SettingsModal
        isOpen={isSettingsModalOpen}
        onClose={() => setIsSettingsModalOpen(false)}
      />
    </div>
  );
}
