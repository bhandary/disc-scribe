"use client";

import { useState, useCallback } from "react";
import { useDropzone } from "react-dropzone";
import Papa from "papaparse";
import { Upload, FileText, AlertCircle, CheckCircle2, Download } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

interface CSVUploadModalProps {
  isOpen: boolean;
  onClose: () => void;
  onUploadComplete: () => void;
}

interface PreviewRow {
  artist: string;
  album_name: string;
  lyricist?: string;
  genre: string;
  num_discs: number;
}

export function CSVUploadModal({ isOpen, onClose, onUploadComplete }: CSVUploadModalProps) {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<PreviewRow[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadResult, setUploadResult] = useState<{
    inserted: number;
    updated: number;
    errors: Array<{ row: number; error: string }>;
  } | null>(null);

  const onDrop = useCallback((acceptedFiles: File[]) => {
    const file = acceptedFiles[0];
    if (!file) return;

    setFile(file);
    setUploadResult(null);

    Papa.parse(file, {
      header: true,
      preview: 5,
      complete: (results) => {
        const rows = results.data as any[];
        const previewData: PreviewRow[] = rows
          .filter((row) => row.artist && row.album_name)
          .map((row) => ({
            artist: row.artist || row.Artist || "",
            album_name: row.album_name || row.album || row.Album || "",
            lyricist: row.lyricist || row.Lyricist || undefined,
            genre: row.genre || row.Genre || "",
            num_discs: parseInt(row.num_discs || row.discs || "1"),
          }));
        setPreview(previewData);
      },
    });
  }, []);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      "text/csv": [".csv"],
    },
    multiple: false,
  });

  const handleUpload = async () => {
    if (!file) return;

    setIsUploading(true);
    try {
      const result = await api.uploadCSV(file);
      setUploadResult(result);
      if (result.errors.length === 0) {
        setTimeout(() => {
          onUploadComplete();
          onClose();
        }, 2000);
      }
    } catch (error) {
      console.error("Upload failed:", error);
    } finally {
      setIsUploading(false);
    }
  };

  const downloadTemplate = () => {
    const csv = "artist,album_name,lyricist,genre,num_discs\nThe Beatles,Abbey Road,John Lennon,Rock,1\n";
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "discvault_template.csv";
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="max-w-2xl max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Import CD Collection from CSV</DialogTitle>
          <DialogDescription>
            Upload a CSV file with your CD collection. Duplicates will be updated automatically.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {/* Download template */}
          <Button onClick={downloadTemplate} variant="ghost" size="sm" className="w-full">
            <Download className="w-4 h-4 mr-2" />
            Download Sample CSV Template
          </Button>

          {/* Dropzone */}
          {!file && (
            <div
              {...getRootProps()}
              className={cn(
                "border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-all",
                isDragActive
                  ? "border-foreground bg-accent"
                  : "border-border bg-card hover:bg-accent"
              )}
            >
              <input {...getInputProps()} />
              <Upload className="w-12 h-12 mx-auto mb-4 text-muted-foreground" />
              <p className="text-sm font-medium">
                {isDragActive ? "Drop your CSV here..." : "Drag & drop CSV file here"}
              </p>
              <p className="text-xs text-muted-foreground mt-1">or click to browse</p>
            </div>
          )}

          {/* File info and preview */}
          {file && !uploadResult && (
            <div className="space-y-3">
              <div className="flex items-center gap-3 rounded-xl border border-border bg-accent p-3">
                <FileText className="h-8 w-8 text-muted-foreground" />
                <div className="flex-1">
                  <p className="font-medium">{file.name}</p>
                  <p className="text-xs text-muted-foreground">
                    {(file.size / 1024).toFixed(2)} KB
                  </p>
                </div>
                <Button
                  onClick={() => {
                    setFile(null);
                    setPreview([]);
                  }}
                  variant="ghost"
                  size="sm"
                >
                  Remove
                </Button>
              </div>

              {/* Preview table */}
              {preview.length > 0 && (
                <div className="overflow-hidden rounded-xl border border-border">
                  <div className="border-b border-border bg-accent px-3 py-2">
                    <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                      Preview (first 5 rows)
                    </p>
                  </div>
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead className="bg-accent/60">
                        <tr>
                          <th className="px-3 py-2 text-left font-medium">Artist</th>
                          <th className="px-3 py-2 text-left font-medium">Album</th>
                          <th className="px-3 py-2 text-left font-medium">Lyricist</th>
                          <th className="px-3 py-2 text-left font-medium">Genre</th>
                          <th className="px-3 py-2 text-left font-medium">Discs</th>
                        </tr>
                      </thead>
                      <tbody>
                        {preview.map((row, idx) => (
                          <tr key={idx} className="border-t border-border">
                            <td className="px-3 py-2">{row.artist}</td>
                            <td className="px-3 py-2">{row.album_name}</td>
                            <td className="px-3 py-2 text-muted-foreground">
                              {row.lyricist || "-"}
                            </td>
                            <td className="px-3 py-2">{row.genre}</td>
                            <td className="px-3 py-2">{row.num_discs}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              <Button
                onClick={handleUpload}
                disabled={isUploading}
                className="w-full"
              >
                {isUploading ? "Uploading..." : "Upload to Collection"}
              </Button>
            </div>
          )}

          {/* Upload result */}
          {uploadResult && (
            <div className="space-y-3">
              <div className="flex items-start gap-3 rounded-xl border border-border bg-accent p-4">
                <CheckCircle2 className="mt-0.5 h-6 w-6 flex-shrink-0 text-foreground" />
                <div>
                  <p className="font-medium">Upload Complete!</p>
                  <p className="text-sm text-muted-foreground mt-1">
                    {uploadResult.inserted} new CDs added, {uploadResult.updated} updated
                  </p>
                </div>
              </div>

              {uploadResult.errors.length > 0 && (
                <div className="border border-red-500/20 rounded-lg overflow-hidden">
                  <div className="bg-red-500/10 px-3 py-2 border-b border-red-500/20 flex items-center gap-2">
                    <AlertCircle className="w-4 h-4 text-red-500" />
                    <p className="text-sm font-medium text-red-500">
                      {uploadResult.errors.length} rows had errors
                    </p>
                  </div>
                  <div className="max-h-40 overflow-y-auto p-3 space-y-2">
                    {uploadResult.errors.map((error, idx) => (
                      <div key={idx} className="text-xs">
                        <span className="text-muted-foreground">Row {error.row}:</span>{" "}
                        <span className="text-red-700">{error.error}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
