import { authHeaders, redirectToLogin } from "@/lib/session";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface SessionUser {
  id: string;
  email?: string | null;
  name?: string | null;
  picture?: string | null;
}

export interface CD {
  id: string;
  artist: string;
  album_name: string;
  lyricist?: string;
  genre: string;
  num_discs: number;
  cover_art_url?: string;
  release_year?: number;
  ai_summary?: string;
  ai_sources?: Array<{ title: string; url: string }>;
  created_at: string;
  updated_at: string;
  needs_enrichment: boolean;
}

export interface SearchResponse {
  cds: CD[];
  total: number;
  page: number;
  limit: number;
  needs_enrichment_count: number;
}

export interface APIKeyStatus {
  tavily_configured: boolean;
  tavily_masked: string;
  anthropic_configured: boolean;
  anthropic_masked: string;
  openai_configured: boolean;
  openai_masked: string;
  llm_model: string;
}

async function readJson<T>(response: Response): Promise<T> {
  if (response.status === 401) {
    redirectToLogin();
    throw new Error("Not signed in");
  }
  if (!response.ok) throw new Error("Request failed");
  return response.json();
}

export const api = {
  googleLoginUrl: `${API_URL}/api/auth/google`,

  async me(): Promise<SessionUser | null> {
    const response = await fetch(`${API_URL}/api/auth/me`, { headers: authHeaders() });
    if (response.status === 401) return null;
    if (!response.ok) throw new Error("Failed to load the signed-in account");
    return response.json();
  },

  async searchCDs(params: {
    q?: string;
    artist?: string;
    album_name?: string;
    lyricist?: string;
    genre?: string;
    page?: number;
    limit?: number;
  }): Promise<SearchResponse> {
    const searchParams = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== "") {
        searchParams.append(key, value.toString());
      }
    });

    const response = await fetch(`${API_URL}/api/cds/search?${searchParams}`, {
      headers: authHeaders(),
    });
    return readJson(response);
  },

  async getCD(id: string): Promise<CD> {
    const response = await fetch(`${API_URL}/api/cds/${id}`, { headers: authHeaders() });
    return readJson(response);
  },

  async uploadCSV(file: File): Promise<{
    inserted: number;
    updated: number;
    errors: Array<{ row: number; error: string }>;
  }> {
    const formData = new FormData();
    formData.append("file", file);

    const response = await fetch(`${API_URL}/api/cds/upload-csv`, {
      method: "POST",
      headers: authHeaders(),
      body: formData,
    });

    return readJson(response);
  },

  async getAPIKeyStatus(): Promise<APIKeyStatus> {
    const response = await fetch(`${API_URL}/api/settings/status`, { headers: authHeaders() });
    return readJson(response);
  },

  async updateAPIKeys(keys: {
    tavily_api_key?: string;
    anthropic_api_key?: string;
    openai_api_key?: string;
    llm_model?: string;
  }): Promise<{ message: string; updated: string[] }> {
    const response = await fetch(`${API_URL}/api/settings/keys`, {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(keys),
    });

    return readJson(response);
  },

  async streamEnrichment(
    cdId: string,
    onEvent: (event: string, data: unknown) => void,
    signal?: AbortSignal,
  ): Promise<void> {
    const response = await fetch(`${API_URL}/api/cds/${cdId}/enrich-stream`, {
      headers: authHeaders(),
      signal,
    });
    if (response.status === 401) {
      redirectToLogin();
      throw new Error("Not signed in");
    }
    if (!response.ok || !response.body) throw new Error("Enrichment failed");

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const frames = buffer.split("\n\n");
      buffer = frames.pop() ?? "";
      for (const frame of frames) {
        let event = "message";
        const dataLines: string[] = [];
        for (const line of frame.split("\n")) {
          if (line.startsWith("event:")) event = line.slice(6).trim();
          else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
        }
        if (!dataLines.length) continue;
        const raw = dataLines.join("\n");
        try {
          onEvent(event, JSON.parse(raw));
        } catch {
          onEvent(event, raw);
        }
      }
    }
  },
};
