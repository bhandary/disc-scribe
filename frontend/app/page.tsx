"use client";

import { useState, useEffect, useCallback } from "react";
import { Upload, Settings, Disc3, Loader2 } from "lucide-react";
import { CDJewelCase } from "@/components/cd-jewel-case";
import { SearchBar, SearchFilter } from "@/components/search-bar";
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
  const [isLoading, setIsLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchFilter, setSearchFilter] = useState<SearchFilter>("all");
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);

  const loadCDs = useCallback(async () => {
    setIsLoading(true);
    try {
      const params: any = { page, limit: 20 };
      
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

  const handleSearch = useCallback((query: string, filter: SearchFilter) => {
    setSearchQuery((prevQuery) => {
      if (prevQuery !== query) {
        setPage(1);
      }
      return query;
    });
    setSearchFilter((prevFilter) => {
      if (prevFilter !== filter) {
        setPage(1);
      }
      return filter;
    });
  }, []);

  const handleCDClick = (cd: CD) => {
    setSelectedCD(cd);
    setIsDrawerOpen(true);
  };

  const handleUploadComplete = () => {
    loadCDs();
  };

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="sticky top-0 z-30 glass border-b border-black/5">
        <div className="container mx-auto px-4 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-primary flex items-center justify-center shadow-sm">
                <Disc3 className="w-6 h-6 text-primary-foreground" />
              </div>
              <div>
                <h1 className="text-xl font-bold">The Rack</h1>
              </div>
            </div>

            <div className="flex items-center gap-2">
              <Button
                onClick={() => setIsUploadModalOpen(true)}
                variant="secondary"
                size="sm"
              >
                <Upload className="w-4 h-4 mr-2" />
                Import CSV
              </Button>
              <Button
                onClick={() => setIsSettingsModalOpen(true)}
                variant="ghost"
                size="icon"
              >
                <Settings className="w-5 h-5" />
              </Button>
            </div>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="container mx-auto px-4 py-8">
        <div className="space-y-8">
          {/* Search */}
          <SearchBar onSearch={handleSearch} className="max-w-2xl mx-auto" />

          {/* Stats */}
          <div className="flex items-center justify-between text-sm">
            <p className="text-muted-foreground">
              {total} {total === 1 ? "CD" : "CDs"} in collection
            </p>
            {isLoading && (
              <div className="flex items-center gap-2 text-vinyl-gold">
                <Loader2 className="w-4 h-4 animate-spin" />
                <span>Loading...</span>
              </div>
            )}
          </div>

          {/* CD Grid */}
          {cds.length === 0 && !isLoading ? (
            <div className="text-center py-20">
              <Disc3 className="w-16 h-16 mx-auto mb-4 text-muted-foreground/20" />
              <h2 className="text-xl font-semibold mb-2">No CDs found</h2>
              <p className="text-muted-foreground mb-6">
                {searchQuery
                  ? "Try a different search term"
                  : "Start by importing your collection"}
              </p>
              <Button onClick={() => setIsUploadModalOpen(true)}>
                <Upload className="w-4 h-4 mr-2" />
                Import CSV
              </Button>
            </div>
          ) : (
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-6">
              {cds.map((cd) => (
                <CDJewelCase key={cd.id} cd={cd} onClick={() => handleCDClick(cd)} />
              ))}
            </div>
          )}

          {/* Pagination */}
          {total > 20 && (
            <div className="flex items-center justify-center gap-2">
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
        </div>
      </main>

      {/* Modals */}
      <DigitalBookletDrawer
        cd={selectedCD}
        isOpen={isDrawerOpen}
        onClose={() => setIsDrawerOpen(false)}
      />
      <CSVUploadModal
        isOpen={isUploadModalOpen}
        onClose={() => setIsUploadModalOpen(false)}
        onUploadComplete={handleUploadComplete}
      />
      <SettingsModal
        isOpen={isSettingsModalOpen}
        onClose={() => setIsSettingsModalOpen(false)}
      />
    </div>
  );
}
