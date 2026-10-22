"use client";

import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { X, Loader2, RefreshCw, Disc3, Trash2 } from "lucide-react";
import { CD, api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import ReactMarkdown from "react-markdown";

function displayLinerNotes(content: string): string {
  return content
    .replace(/^\s*#{1,6}\s*Digital Liner Notes:?\s*/i, "")
    .replace(/^\s*\*{0,2}Digital Liner Notes:\*{0,2}\s*/i, "")
    .replace(/\n+#{1,6}\s*Verified Sources\b[\s\S]*$/i, "")
    .replace(/\n+\*{0,2}Verified Sources\*{0,2}\s*[\s\S]*$/i, "")
    .trim();
}

interface DigitalBookletDrawerProps {
  cd: CD | null;
  isOpen: boolean;
  onClose: () => void;
  onDeleted?: (id: string) => void;
}

interface EnrichmentState {
  status: "idle" | "planning" | "searching" | "synthesizing" | "complete" | "error";
  message: string;
  content: string;
  sources: Array<{ title: string; url: string }>;
}

export function DigitalBookletDrawer({ cd, isOpen, onClose, onDeleted }: DigitalBookletDrawerProps) {
  const [enrichmentState, setEnrichmentState] = useState<EnrichmentState>({
    status: "idle",
    message: "",
    content: "",
    sources: [],
  });
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const startEnrichment = (cdId: string) => {
    setEnrichmentState({
      status: "planning",
      message: "Initializing Deep Agent...",
      content: "",
      sources: [],
    });

    const eventSource = api.enrichCDStream(cdId);

    // Parse SSE payloads defensively: a single malformed event must not crash
    // the whole drawer (which would fall through to onerror -> "Connection error").
    const parseEvent = <T,>(event: MessageEvent, name: string): T | null => {
      try {
        return JSON.parse(event.data) as T;
      } catch (err) {
        console.warn(`Skipping malformed SSE '${name}' event:`, event.data, err);
        return null;
      }
    };

    eventSource.addEventListener("plan", (event: MessageEvent) => {
      const data = parseEvent<{ status?: string; queries?: string[] }>(event, "plan");
      if (!data) return;
      setEnrichmentState((prev) => ({
        ...prev,
        status: "planning",
        message: data.status || `Planning: ${data.queries?.join(", ")}`,
      }));
    });

    eventSource.addEventListener("tool_call", (event: MessageEvent) => {
      const data = parseEvent<{ query: string }>(event, "tool_call");
      if (!data) return;
      setEnrichmentState((prev) => ({
        ...prev,
        status: "searching",
        message: `Searching: ${data.query}`,
      }));
    });

    eventSource.addEventListener("token", (event: MessageEvent) => {
      const data = parseEvent<{ content: string }>(event, "token");
      if (!data) return;
      setEnrichmentState((prev) => ({
        ...prev,
        status: "synthesizing",
        message: "Generating Digital Liner Notes...",
        content: prev.content + data.content,
      }));
    });

    eventSource.addEventListener("complete", (event: MessageEvent) => {
      const data = parseEvent<{ summary: string; sources?: Array<{ title: string; url: string }> }>(event, "complete");
      if (!data) return;
      setEnrichmentState((prev) => ({
        status: "complete",
        message: "Enrichment complete!",
        // Prefer the final summary, but fall back to the tokens we already
        // streamed so a partial LLM stream still shows something.
        content: data.summary && data.summary.trim() ? data.summary : prev.content,
        sources: data.sources || [],
      }));
      eventSource.close();
    });

    // Per-query search failures: show in the status line but keep streaming;
    // the agent will fall back to general knowledge or other successful queries.
    eventSource.addEventListener("search_error", (event: MessageEvent) => {
      const data = parseEvent<{ query?: string; message?: string }>(event, "search_error");
      if (!data) return;
      setEnrichmentState((prev) => ({
        ...prev,
        message: `Search skipped (${data.query ?? "query"}): ${data.message ?? "error"}`,
      }));
    });

    eventSource.addEventListener("error", (event: MessageEvent) => {
      const data = parseEvent<{ message?: string }>(event, "error");
      setEnrichmentState((prev) => ({
        ...prev,
        status: "error",
        message: data?.message || "Enrichment failed",
      }));
      eventSource.close();
    });

    eventSource.onerror = () => {
      setEnrichmentState((prev) => ({
        ...prev,
        status: "error",
        message: "Connection error",
      }));
      eventSource.close();
    };
  };

  const handleDelete = async () => {
    if (!cd) return;
    if (!confirmDelete) {
      setConfirmDelete(true);
      return;
    }
    setIsDeleting(true);
    setDeleteError(null);
    try {
      await api.deleteCD(cd.id);
      onDeleted?.(cd.id);
      onClose();
    } catch (error) {
      setDeleteError(error instanceof Error ? error.message : "Failed to delete album");
    } finally {
      setIsDeleting(false);
    }
  };

  useEffect(() => {
    setConfirmDelete(false);
    setDeleteError(null);
    setIsDeleting(false);
  }, [cd?.id, isOpen]);

  useEffect(() => {
    if (cd && isOpen) {
      if (cd.ai_summary && cd.ai_summary.trim()) {
        setEnrichmentState({
          status: "complete",
          message: "Cached liner notes",
          content: cd.ai_summary,
          sources: cd.ai_sources || [],
        });
      } else {
        startEnrichment(cd.id);
      }
    }
  }, [cd, isOpen]);

  if (!cd) return null;

  return (
    <AnimatePresence>
      {isOpen && (
        <>
          {/* Overlay */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="fixed inset-0 bg-black/30 backdrop-blur-sm z-40"
          />
          
          {/* Drawer */}
          <motion.div
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ type: "spring", damping: 30, stiffness: 300 }}
            className="fixed right-0 top-0 h-full w-full md:w-2/3 lg:w-1/2 bg-white border-l border-black/10 z-50 overflow-y-auto"
          >
            <div className="p-6 space-y-6">
              {/* Header */}
              <div className="flex items-start justify-between">
                <div className="flex gap-4">
                  {cd.cover_art_url ? (
                    <img
                      src={cd.cover_art_url}
                      alt={cd.album_name}
                      className="w-20 h-20 rounded-lg object-cover"
                    />
                  ) : (
                    <div className="w-20 h-20 rounded-lg bg-muted flex items-center justify-center">
                      <Disc3 className="w-8 h-8 text-muted-foreground/40" />
                    </div>
                  )}
                  <div>
                    <h2 className="text-2xl font-bold">{cd.album_name}</h2>
                    <p className="text-muted-foreground">{cd.artist}</p>
                    {cd.lyricist && (
                      <p className="text-sm text-vinyl-silver">Lyrics by {cd.lyricist}</p>
                    )}
                  </div>
                </div>
                <Button variant="ghost" size="icon" onClick={onClose}>
                  <X className="w-5 h-5" />
                </Button>
              </div>

              {/* Activity Stepper */}
              {enrichmentState.status !== "complete" && enrichmentState.status !== "idle" && (
                <div className="bg-muted border border-black/5 rounded-2xl p-4">
                  <div className="flex items-center gap-3">
                    {enrichmentState.status === "error" ? (
                      <div className="w-8 h-8 rounded-full bg-red-500/20 flex items-center justify-center">
                        <X className="w-4 h-4 text-red-500" />
                      </div>
                    ) : (
                      <Loader2 className="w-8 h-8 animate-spin text-vinyl-gold" />
                    )}
                    <div>
                      <p className="font-medium">
                        {enrichmentState.status === "planning" && "Planning research..."}
                        {enrichmentState.status === "searching" && "Searching knowledge base..."}
                        {enrichmentState.status === "synthesizing" && "Synthesizing insights..."}
                        {enrichmentState.status === "error" && "Enrichment failed"}
                      </p>
                      <p className="text-sm text-muted-foreground">{enrichmentState.message}</p>
                    </div>
                  </div>
                </div>
              )}

              {/* Content */}
              {enrichmentState.content && (
                <div className="prose prose-neutral max-w-none">
                  <ReactMarkdown>{displayLinerNotes(enrichmentState.content)}</ReactMarkdown>
                </div>
              )}

              {/* Regenerate button */}
              {enrichmentState.status === "complete" && (
                <Button
                  onClick={() => startEnrichment(cd.id)}
                  variant="secondary"
                  className="w-full"
                >
                  <RefreshCw className="w-4 h-4 mr-2" />
                  Regenerate Insights
                </Button>
              )}

              <div className="pt-2 border-t border-black/5 space-y-2">
                {deleteError && (
                  <p className="text-sm text-red-600">{deleteError}</p>
                )}
                <Button
                  onClick={handleDelete}
                  variant="destructive"
                  className="w-full"
                  disabled={isDeleting}
                >
                  {isDeleting ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <Trash2 className="w-4 h-4 mr-2" />
                  )}
                  {confirmDelete ? "Remove from The Rack?" : "Delete album"}
                </Button>
                {confirmDelete && !isDeleting && (
                  <Button
                    onClick={() => setConfirmDelete(false)}
                    variant="ghost"
                    className="w-full"
                  >
                    Cancel
                  </Button>
                )}
              </div>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
