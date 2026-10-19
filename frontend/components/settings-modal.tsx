"use client";

import { useState, useEffect } from "react";
import { Settings, CheckCircle, AlertCircle, Loader2 } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api, APIKeyStatus } from "@/lib/api";
import { cn } from "@/lib/utils";

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export function SettingsModal({ isOpen, onClose }: SettingsModalProps) {
  const [status, setStatus] = useState<APIKeyStatus | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  
  const [tavilyKey, setTavilyKey] = useState("");
  const [anthropicKey, setAnthropicKey] = useState("");
  const [openaiKey, setOpenaiKey] = useState("");
  const [llmModel, setLlmModel] = useState("claude-3-7-sonnet-latest");

  useEffect(() => {
    if (isOpen) {
      loadStatus();
    }
  }, [isOpen]);

  const loadStatus = async () => {
    setIsLoading(true);
    try {
      const data = await api.getAPIKeyStatus();
      setStatus(data);
      setLlmModel(data.llm_model);
    } catch (error) {
      console.error("Failed to load API key status:", error);
    } finally {
      setIsLoading(false);
    }
  };

  const handleSave = async () => {
    setIsSaving(true);
    try {
      const updates: any = {};
      if (tavilyKey) updates.tavily_api_key = tavilyKey;
      if (anthropicKey) updates.anthropic_api_key = anthropicKey;
      if (openaiKey) updates.openai_api_key = openaiKey;
      if (llmModel) updates.llm_model = llmModel;

      await api.updateAPIKeys(updates);
      
      setTavilyKey("");
      setAnthropicKey("");
      setOpenaiKey("");
      
      await loadStatus();
      
      setTimeout(() => {
        onClose();
      }, 1000);
    } catch (error) {
      console.error("Failed to save API keys:", error);
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Settings className="w-5 h-5" />
            API Configuration
          </DialogTitle>
          <DialogDescription>
            Configure API keys for AI enrichment. Keys are encrypted and stored securely.
          </DialogDescription>
        </DialogHeader>

        {isLoading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="w-8 h-8 animate-spin text-vinyl-gold" />
          </div>
        ) : (
          <div className="space-y-4">
            {/* Tavily Key */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <label className="text-sm font-medium">Tavily API Key</label>
                <StatusBadge configured={status?.tavily_configured} />
              </div>
              <Input
                type="password"
                placeholder={status?.tavily_masked || "tvly-xxxxx"}
                value={tavilyKey}
                onChange={(e) => setTavilyKey(e.target.value)}
              />
              <p className="text-xs text-muted-foreground">
                Required for web search. Get yours at{" "}
                <a
                  href="https://tavily.com"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-vinyl-gold hover:underline"
                >
                  tavily.com
                </a>
              </p>
            </div>

            {/* Anthropic Key */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <label className="text-sm font-medium">Anthropic API Key</label>
                <StatusBadge configured={status?.anthropic_configured} />
              </div>
              <Input
                type="password"
                placeholder={status?.anthropic_masked || "sk-ant-xxxxx"}
                value={anthropicKey}
                onChange={(e) => setAnthropicKey(e.target.value)}
              />
              <p className="text-xs text-muted-foreground">
                For Claude models. Get yours at{" "}
                <a
                  href="https://console.anthropic.com"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-vinyl-gold hover:underline"
                >
                  console.anthropic.com
                </a>
              </p>
            </div>

            {/* OpenAI Key */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <label className="text-sm font-medium">OpenAI API Key</label>
                <StatusBadge configured={status?.openai_configured} />
              </div>
              <Input
                type="password"
                placeholder={status?.openai_masked || "sk-xxxxx"}
                value={openaiKey}
                onChange={(e) => setOpenaiKey(e.target.value)}
              />
              <p className="text-xs text-muted-foreground">
                For GPT models. Get yours at{" "}
                <a
                  href="https://platform.openai.com"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-vinyl-gold hover:underline"
                >
                  platform.openai.com
                </a>
              </p>
            </div>

            {/* LLM Model */}
            <div className="space-y-2">
              <label className="text-sm font-medium">Preferred LLM Model</label>
              <select
                value={llmModel}
                onChange={(e) => setLlmModel(e.target.value)}
                className="flex h-10 w-full rounded-md border border-white/10 bg-white/5 px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <option value="claude-3-7-sonnet-latest">Claude 3.7 Sonnet (Latest)</option>
                <option value="claude-3-5-sonnet-latest">Claude 3.5 Sonnet</option>
                <option value="gpt-4o">GPT-4o</option>
                <option value="gpt-4o-mini">GPT-4o Mini</option>
              </select>
            </div>

            {/* Save button */}
            <Button
              onClick={handleSave}
              disabled={isSaving}
              className="w-full"
            >
              {isSaving ? (
                <>
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  Saving...
                </>
              ) : (
                "Save Configuration"
              )}
            </Button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

function StatusBadge({ configured }: { configured?: boolean }) {
  if (configured === undefined) return null;
  
  return (
    <div
      className={cn(
        "flex items-center gap-1 text-xs px-2 py-1 rounded-full",
        configured
          ? "bg-green-500/20 text-green-400"
          : "bg-amber-500/20 text-amber-400"
      )}
    >
      {configured ? (
        <>
          <CheckCircle className="w-3 h-3" />
          <span>Configured</span>
        </>
      ) : (
        <>
          <AlertCircle className="w-3 h-3" />
          <span>Not set</span>
        </>
      )}
    </div>
  );
}
