"use client";

import { Check, Disc3 } from "lucide-react";
import { CD } from "@/lib/api";

interface CDJewelCaseProps {
  cd: CD;
  onClick?: () => void;
}

const SPINE_COLORS = ["#4C1D2C", "#243044", "#3E4A2E", "#5A3A28", "#3C2A4A", "#1E3D3A", "#4A3228"];

export function spineColor(seed: string) {
  let hash = 0;
  for (const char of seed) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  return SPINE_COLORS[hash % SPINE_COLORS.length];
}

export function CDSpine({ cd, onClick }: CDJewelCaseProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={`${cd.album_name} — ${cd.artist}`}
      className="h-32 w-10 shrink-0 rounded-md text-[11px] font-medium leading-tight text-[#F6F1E8] shadow-sm"
      style={{ backgroundColor: spineColor(cd.album_name + cd.artist) }}
    >
      <span className="block h-full overflow-hidden px-1 py-3 [writing-mode:vertical-rl] rotate-180">
        {cd.album_name}
      </span>
    </button>
  );
}

export function CDJewelCase({ cd, onClick }: CDJewelCaseProps) {
  const meta = [
    cd.release_year ? String(cd.release_year) : null,
    cd.lyricist ? `Lyrics by ${cd.lyricist}` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <button
      type="button"
      onClick={onClick}
      className="flex w-full gap-3 rounded-2xl border border-border bg-card p-3 text-left shadow-card transition-shadow hover:shadow-md"
    >
      {cd.cover_art_url ? (
        <img
          src={cd.cover_art_url}
          alt=""
          className="h-16 w-12 shrink-0 rounded-md object-cover"
        />
      ) : (
        <span
          className="flex h-16 w-12 shrink-0 items-center justify-center rounded-md text-[#F6F1E8]"
          style={{ backgroundColor: spineColor(cd.album_name + cd.artist) }}
          aria-hidden
        >
          <Disc3 className="h-5 w-5 opacity-80" />
        </span>
      )}

      <span className="min-w-0 flex-1">
        <span className="block truncate font-semibold text-foreground">{cd.album_name}</span>
        <span className="mt-0.5 block truncate text-sm text-muted-foreground">{cd.artist}</span>
        <span className="mt-2 flex flex-wrap gap-1.5">
          <span className="chip">{cd.genre}</span>
          <span className="chip">
            {cd.num_discs} {cd.num_discs === 1 ? "disc" : "discs"}
          </span>
          <span className="chip">
            {cd.needs_enrichment ? (
              "Needs liner notes"
            ) : (
              <>
                <Check className="h-3 w-3" aria-hidden />
                Liner notes
              </>
            )}
          </span>
        </span>
        {meta ? (
          <span className="mt-2 block truncate text-[11px] text-muted-foreground">{meta}</span>
        ) : null}
      </span>
    </button>
  );
}
