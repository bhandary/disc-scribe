"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ScanBarcode, Loader2, Disc3, Keyboard } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api, BarcodeLookup, CD } from "@/lib/api";
import { cn } from "@/lib/utils";

interface BarcodeScanModalProps {
  isOpen: boolean;
  onClose: () => void;
  onAdded: (cd: CD) => void;
  onViewExisting?: (id: string) => void;
}

export function BarcodeScanModal({
  isOpen,
  onClose,
  onAdded,
  onViewExisting,
}: BarcodeScanModalProps) {
  const [barcode, setBarcode] = useState("");
  const [match, setMatch] = useState<BarcodeLookup | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [cameraError, setCameraError] = useState<string | null>(null);
  const [isLookingUp, setIsLookingUp] = useState(false);
  const [isAdding, setIsAdding] = useState(false);
  const scannerRef = useRef<{ stop: () => Promise<void> } | null>(null);
  const lookingUpRef = useRef(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const stopScanner = useCallback(async () => {
    const scanner = scannerRef.current;
    scannerRef.current = null;
    if (scanner) {
      try {
        await scanner.stop();
      } catch {
        // already stopped
      }
    }
  }, []);

  const lookup = useCallback(async (raw: string) => {
    const digits = raw.replace(/\D/g, "");
    if (digits.length < 8 || lookingUpRef.current) return;

    lookingUpRef.current = true;
    setIsLookingUp(true);
    setError(null);
    await stopScanner();

    try {
      const result = await api.lookupBarcode(digits);
      setMatch(result);
      setBarcode(result.barcode);
    } catch (err) {
      setMatch(null);
      setError(err instanceof Error ? err.message : "Lookup failed");
    } finally {
      lookingUpRef.current = false;
      setIsLookingUp(false);
    }
  }, [stopScanner]);

  useEffect(() => {
    if (!isOpen || match || isLookingUp) {
      return;
    }

    let cancelled = false;

    const startCamera = async () => {
      try {
        const { Html5Qrcode, Html5QrcodeSupportedFormats } = await import("html5-qrcode");
        if (cancelled) return;

        const cameras = await Html5Qrcode.getCameras();
        if (!cameras.length) {
          setCameraError("No camera found. Type the barcode instead.");
          inputRef.current?.focus();
          return;
        }

        const rear = cameras.find((cam) => /back|rear|environment/i.test(cam.label));
        const scanner = new Html5Qrcode("barcode-reader", {
          verbose: false,
          formatsToSupport: [
            Html5QrcodeSupportedFormats.EAN_13,
            Html5QrcodeSupportedFormats.EAN_8,
            Html5QrcodeSupportedFormats.UPC_A,
            Html5QrcodeSupportedFormats.UPC_E,
            Html5QrcodeSupportedFormats.CODE_128,
          ],
        });
        scannerRef.current = scanner;
        await scanner.start(
          rear?.id || cameras[0].id,
          {
            fps: 8,
            qrbox: { width: 260, height: 120 },
            aspectRatio: 1.777,
          },
          (text) => {
            if (!cancelled) {
              void lookup(text);
            }
          },
          () => undefined
        );
      } catch {
        if (!cancelled) {
          setCameraError("Camera unavailable. Type the barcode instead.");
          inputRef.current?.focus();
        }
      }
    };

    void startCamera();

    return () => {
      cancelled = true;
      void stopScanner();
    };
  }, [isOpen, match, isLookingUp, lookup, stopScanner]);

  useEffect(() => {
    if (!isOpen) {
      setBarcode("");
      setMatch(null);
      setError(null);
      setCameraError(null);
      setIsLookingUp(false);
      setIsAdding(false);
      lookingUpRef.current = false;
    }
  }, [isOpen]);

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    void lookup(barcode);
  };

  const handleAdd = async () => {
    if (!match || match.already_in_collection) return;
    setIsAdding(true);
    setError(null);
    try {
      const cd = await api.addFromBarcode(match.barcode);
      onAdded(cd);
      onClose();
    } catch (err) {
      const existingId = (err as { existingId?: string }).existingId;
      if (existingId && onViewExisting) {
        onViewExisting(existingId);
        onClose();
        return;
      }
      setError(err instanceof Error ? err.message : "Could not add CD");
    } finally {
      setIsAdding(false);
    }
  };

  const handleScanAnother = () => {
    setMatch(null);
    setError(null);
    setBarcode("");
    setCameraError(null);
  };

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-lg max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <ScanBarcode className="w-5 h-5" />
            Scan a CD
          </DialogTitle>
          <DialogDescription>
            Point the camera at the barcode on the case, or type the number.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div
            className={cn(
              "relative overflow-hidden rounded-xl border border-black/10 bg-muted",
              match ? "hidden" : "block"
            )}
          >
            <div id="barcode-reader" className="min-h-[180px] overflow-hidden [&>video]:w-full" />
            {cameraError && (
              <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 p-6 text-center">
                <Keyboard className="w-8 h-8 text-muted-foreground" />
                <p className="text-sm text-muted-foreground">{cameraError}</p>
              </div>
            )}
          </div>

          {!match && (
            <form onSubmit={handleSubmit} className="flex gap-2">
              <Input
                ref={inputRef}
                inputMode="numeric"
                autoComplete="off"
                placeholder="e.g. 5099969943326"
                value={barcode}
                onChange={(e) => setBarcode(e.target.value.replace(/[^\d]/g, ""))}
                className="font-mono tracking-wide"
              />
              <Button type="submit" disabled={barcode.length < 8 || isLookingUp}>
                {isLookingUp ? <Loader2 className="w-4 h-4 animate-spin" /> : "Look up"}
              </Button>
            </form>
          )}

          {isLookingUp && !match && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="w-4 h-4 animate-spin text-vinyl-gold" />
              Searching MusicBrainz and Discogs…
            </div>
          )}

          {error && (
            <p className="text-sm text-red-600 bg-red-50 border border-red-100 rounded-lg px-3 py-2">
              {error}
            </p>
          )}

          {match && (
            <div className="space-y-4">
              <div className="flex gap-4">
                {match.cover_art_url ? (
                  <img
                    src={match.cover_art_url}
                    alt={match.album_name}
                    className="w-24 h-24 rounded-lg object-cover shadow-sm"
                  />
                ) : (
                  <div className="w-24 h-24 rounded-lg bg-muted flex items-center justify-center">
                    <Disc3 className="w-8 h-8 text-muted-foreground/40" />
                  </div>
                )}
                <div className="min-w-0 space-y-1">
                  <h3 className="font-semibold leading-tight">{match.album_name}</h3>
                  <p className="text-sm text-muted-foreground">{match.artist}</p>
                  <p className="text-xs text-muted-foreground">
                    {[match.label, match.release_year, match.genre]
                      .filter(Boolean)
                      .join(" · ")}
                  </p>
                  <p className="text-xs font-mono text-muted-foreground">{match.barcode}</p>
                  <p className="text-[11px] uppercase tracking-wider text-muted-foreground">
                    via {match.source === "musicbrainz" ? "MusicBrainz" : "Discogs"}
                  </p>
                </div>
              </div>

              {match.tracks.length > 0 && (
                <div className="border border-black/10 rounded-lg overflow-hidden max-h-48 overflow-y-auto">
                  <div className="bg-muted px-3 py-2 border-b border-black/10">
                    <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                      {match.tracks.length} tracks
                      {match.num_discs > 1 ? ` · ${match.num_discs} discs` : ""}
                    </p>
                  </div>
                  <ol className="divide-y divide-black/5">
                    {match.tracks.map((track, idx) => (
                      <li key={`${track.position}-${idx}`} className="flex items-baseline gap-3 px-3 py-1.5 text-sm">
                        <span className="w-8 shrink-0 font-mono text-xs text-muted-foreground">
                          {track.position}
                        </span>
                        <span className="flex-1 truncate">{track.title}</span>
                        {track.duration && (
                          <span className="font-mono text-xs text-muted-foreground">
                            {track.duration}
                          </span>
                        )}
                      </li>
                    ))}
                  </ol>
                </div>
              )}

              {match.already_in_collection ? (
                <div className="space-y-2">
                  <p className="text-sm text-accent">This CD is already on The Rack.</p>
                  <div className="flex gap-2">
                    {match.existing_id && onViewExisting && (
                      <Button
                        className="flex-1"
                        onClick={() => {
                          onViewExisting(match.existing_id!);
                          onClose();
                        }}
                      >
                        View in collection
                      </Button>
                    )}
                    <Button variant="secondary" onClick={handleScanAnother}>
                      Scan another
                    </Button>
                  </div>
                </div>
              ) : (
                <div className="flex gap-2">
                  <Button className="flex-1" onClick={handleAdd} disabled={isAdding}>
                    {isAdding ? (
                      <>
                        <Loader2 className="w-4 h-4 animate-spin" />
                        Adding…
                      </>
                    ) : (
                      "Add to The Rack"
                    )}
                  </Button>
                  <Button variant="secondary" onClick={handleScanAnother} disabled={isAdding}>
                    Scan another
                  </Button>
                </div>
              )}
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
