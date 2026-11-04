"use client";

import { motion } from "framer-motion";
import { Disc3, Play } from "lucide-react";
import { CD } from "@/lib/api";
import { cn } from "@/lib/utils";

interface CDJewelCaseProps {
  cd: CD;
  onClick?: () => void;
}

export function CDJewelCase({ cd, onClick }: CDJewelCaseProps) {
  return (
    <motion.div
      whileHover={{ scale: 1.05, rotateY: 5 }}
      whileTap={{ scale: 0.98 }}
      transition={{ type: "spring", stiffness: 300, damping: 20 }}
      onClick={onClick}
      className="cursor-pointer group"
    >
      <div className="jewel-case aspect-square overflow-hidden relative">
        {/* Spine ridge */}
        <div className="jewel-spine" />
        
        {/* Cover art or placeholder */}
        <div className="relative w-full h-full p-4">
          {cd.cover_art_url ? (
            <img
              src={cd.cover_art_url}
              alt={`${cd.album_name} cover`}
              className="w-full h-full object-cover rounded"
            />
          ) : (
            <div className="w-full h-full flex items-center justify-center bg-gradient-to-br from-zinc-800 to-zinc-900 rounded">
              <Disc3 className="w-16 h-16 text-vinyl-gold/20" />
            </div>
          )}
          
          {/* Plastic glare effect */}
          <div className="absolute inset-0 bg-gradient-to-br from-white/5 via-transparent to-transparent pointer-events-none rounded" />
          
          {/* Hover overlay */}
          <motion.div
            initial={{ opacity: 0 }}
            whileHover={{ opacity: 1 }}
            className="absolute inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center rounded"
          >
            <Play className="w-12 h-12 text-vinyl-gold" />
          </motion.div>
        </div>
        
        {/* Multi-disc badge */}
        {cd.num_discs > 1 && (
          <div className="absolute top-2 right-2 bg-vinyl-gold text-vinyl-obsidian text-xs font-bold px-2 py-1 rounded shadow-lg">
            {cd.num_discs}xCD
          </div>
        )}
        
        {/* Needs enrichment indicator */}
        {cd.needs_enrichment && (
          <div className="absolute bottom-2 right-2 w-2 h-2 bg-amber-400 rounded-full animate-pulse" />
        )}
      </div>
      
      {/* Info */}
      <div className="mt-3 space-y-1">
        <h3 className="font-semibold text-sm truncate group-hover:text-vinyl-gold transition-colors">
          {cd.album_name}
        </h3>
        <p className="text-xs text-muted-foreground truncate">{cd.artist}</p>
        <div className="flex items-center gap-2 text-xs">
          <span className="px-2 py-0.5 bg-white/5 rounded">{cd.genre}</span>
          {cd.release_year && (
            <span className="text-muted-foreground">{cd.release_year}</span>
          )}
        </div>
      </div>
    </motion.div>
  );
}
