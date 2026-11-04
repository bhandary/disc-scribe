"use client";

import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { X, Loader2, ExternalLink, RefreshCw, Disc3 } from "lucide-react";
import { CD, api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import ReactMarkdown from "react-markdown";

interface DigitalBookletDrawerProps {
  cd: CD | null;
  isOpen: boolean;
  onClose: () => void;
}

interface EnrichmentState {
  status: "idle" | "planning" | "searching" | "synthesizing" | "complete" | "error";
  message: string;
  content: string;
  sources: Array<{ title: string; url: string }>;
}

export function DigitalBookletDrawer({ cd, isOpen, onClose }: DigitalBookletDrawerProps) {
  const [enrichmentState, setEnrichmentState] = useState<EnrichmentState>({
    status: "idle",
    message: "",
    content: "",
    sources: [],
  });

  const startEnrichment = (cdId: string) => {
    setEnrichmentState({
      status: "planning",
      message: "Initializing Deep Agent...",
      content: "",
      sources: [],
    });

    const eventSource = api.enrichCDStream(cdId);

    eventSource.addEventListener("plan", (event: MessageEvent) => {
      const data = JSON.parse(event.data);
      setEnrichmentState((prev) => ({
        ...prev,
        status: "planning",
        message: data.status || `Planning: ${data.queries?.join(", ")}`,
      }));
    });

    eventSource.addEventListener("tool_call", (event: MessageEvent) => {
      const data = JSON.parse(event.data);
      setEnrichmentState((prev) => ({
        ...prev,
        status: "searching",
        message: `Searching: ${data.query}`,
      }));
    });

    eventSource.addEventListener("token", (event: MessageEvent) => {
      const data = JSON.parse(event.data);
      setEnrichmentState((prev) => ({
        ...prev,
        status: "synthesizing",
        message: "Generating Digital Liner Notes...",
        content: prev.content + data.content,
      }));
    });

    eventSource.addEventListener("complete", (event: MessageEvent) => {
      const data = JSON.parse(event.data);
      setEnrichmentState({
        status: "complete",
        message: "Enrichment complete!",
        content: data.summary,
        sources: data.sources || [],
      });
      eventSource.close();
    });

    eventSource.addEventListener("error", (event: MessageEvent) => {
      const data = JSON.parse(event.data);
      setEnrichmentState((prev) => ({
        ...prev,
        status: "error",
        message: data.message || "Enrichment failed",
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

  useEffect(() => {
    if (cd && isOpen) {
      if (cd.ai_summary) {
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
            className="fixed inset-0 z-40 bg-stone-900/25"
          />
          
          {/* Drawer */}
          <motion.div
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ type: "spring", damping: 30, stiffness: 300 }}
            className="fixed right-0 top-0 z-50 h-full w-full max-w-lg overflow-y-auto border-l border-border bg-background"
          >
            <div className="p-6 space-y-6">
              {/* Header */}
              <div className="flex items-start justify-between">
                <div className="flex gap-4">
                  {cd.cover_art_url ? (
                    <img
                      src={cd.cover_art_url}
                      alt={cd.album_name}
                      className="h-20 w-16 rounded-md object-cover"
                    />
                  ) : (
                    <div className="flex h-20 w-16 items-center justify-center rounded-md bg-stone-300 text-stone-600">
                      <Disc3 className="h-6 w-6" />
                    </div>
                  )}
                  <div>
                    <h2 className="font-serif text-3xl font-medium leading-tight">{cd.album_name}</h2>
                    <p className="mt-1 text-muted-foreground">{cd.artist}</p>
                    {cd.lyricist && (
                      <p className="text-sm text-muted-foreground">Lyrics by {cd.lyricist}</p>
                    )}
                  </div>
                </div>
                <Button variant="ghost" size="icon" onClick={onClose}>
                  <X className="w-5 h-5" />
                </Button>
              </div>

              {/* Activity Stepper */}
              {enrichmentState.status !== "complete" && enrichmentState.status !== "idle" && (
                <div className="rounded-2xl border border-border bg-card p-4 shadow-card">
                  <div className="flex items-center gap-3">
                    {enrichmentState.status === "error" ? (
                      <div className="w-8 h-8 rounded-full bg-red-500/20 flex items-center justify-center">
                        <X className="w-4 h-4 text-red-500" />
                      </div>
                    ) : (
                      <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
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
                <div className="liner-notes max-w-none">
                  <ReactMarkdown>{enrichmentState.content}</ReactMarkdown>
                </div>
              )}

              {/* Sources */}
              {enrichmentState.sources.length > 0 && (
                <div className="space-y-2">
                  <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">
                    Verified Sources
                  </h3>
                  <div className="flex flex-wrap gap-2">
                    {enrichmentState.sources.map((source, idx) => (
                      <a
                        key={idx}
                        href={source.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="chip transition-colors hover:bg-stone-200"
                      >
                        <span className="truncate max-w-[200px]">{source.title}</span>
                        <ExternalLink className="w-3 h-3 flex-shrink-0" />
                      </a>
                    ))}
                  </div>
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
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
