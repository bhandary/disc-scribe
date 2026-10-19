const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

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

export const api = {
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
    
    const response = await fetch(`${API_URL}/api/cds/search?${searchParams}`);
    if (!response.ok) throw new Error("Search failed");
    return response.json();
  },

  async getCD(id: string): Promise<CD> {
    const response = await fetch(`${API_URL}/api/cds/${id}`);
    if (!response.ok) throw new Error("Failed to fetch CD");
    return response.json();
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
      body: formData,
    });
    
    if (!response.ok) throw new Error("Upload failed");
    return response.json();
  },

  async getAPIKeyStatus(): Promise<APIKeyStatus> {
    const response = await fetch(`${API_URL}/api/settings/status`);
    if (!response.ok) throw new Error("Failed to fetch API key status");
    return response.json();
  },

  async updateAPIKeys(keys: {
    tavily_api_key?: string;
    anthropic_api_key?: string;
    openai_api_key?: string;
    llm_model?: string;
  }): Promise<{ message: string; updated: string[] }> {
    const response = await fetch(`${API_URL}/api/settings/keys`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(keys),
    });
    
    if (!response.ok) throw new Error("Failed to update API keys");
    return response.json();
  },

  enrichCDStream(cdId: string): EventSource {
    return new EventSource(`${API_URL}/api/cds/${cdId}/enrich-stream`);
  },
};
