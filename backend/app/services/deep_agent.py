from typing import AsyncIterator, Dict, Any, Optional
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.tools import tool
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from typing_extensions import TypedDict
import asyncio
import json

from app.services.brave_search import BraveSearchService


# Brave Search Free plan allows 1 request/second. Slightly over to be safe.
BRAVE_RATE_LIMIT_DELAY_SECONDS = 1.1


def _extract_text(content: Any) -> str:
    """
    Normalize a LangChain message chunk's `.content` to a plain text string.

    Modern Claude models (Haiku 5.5, Sonnet 4.5+, Opus 4.5+) stream chunks
    whose `content` is a list of content blocks like
        [{"type": "text", "text": "..."},
         {"type": "thinking", "thinking": "..."}]
    rather than a bare string. Concatenating that list with `+=` raises
    `can only concatenate str (not "list") to str`, which silently killed
    the synthesis stream. We keep only visible text here; thinking blocks
    are internal reasoning and shouldn't leak into the liner notes.
    """
    if not content:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                btype = block.get("type")
                if btype == "text":
                    parts.append(block.get("text", ""))
                # Deliberately ignore 'thinking', 'tool_use', etc.
        return "".join(parts)
    return str(content)


class AgentState(TypedDict):
    messages: list
    plan: Optional[str]
    research_data: Dict[str, Any]
    final_report: Optional[str]
    sources: list


class DeepAgentEnricher:
    """Deep Agent for enriching CD information using LangGraph"""
    
    def __init__(
        self,
        brave_key: str,
        anthropic_key: Optional[str] = None,
        openai_key: Optional[str] = None,
        model: str = "claude-haiku-5-5"
    ):
        self.brave_key = brave_key

        # Initialize LLM based on model. Note: newer Claude models (Haiku 5.5,
        # Opus 4.x+, reasoning-tier Sonnets) reject the `temperature` param, so
        # we omit it and let each model use its own default.
        if "claude" in model.lower() and anthropic_key:
            # Haiku 5.5 / newer Claude models stream thinking blocks first.
            # Turn thinking off so astream() yields visible text, not only
            # {"type": "thinking"} chunks that our extractor correctly skips.
            self.llm = ChatAnthropic(
                model=model,
                anthropic_api_key=anthropic_key,
                thinking={"type": "disabled"},
            )
        elif openai_key:
            self.llm = ChatOpenAI(
                model=model if "gpt" in model.lower() else "gpt-4o",
                openai_api_key=openai_key,
                temperature=0.7,
            )
        else:
            raise ValueError("No valid API key provided for LLM")
    
    async def enrich_cd_stream(
        self,
        artist: str,
        album_name: str,
        lyricist: Optional[str],
        genre: str
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        Stream enrichment process events
        Yields: {"type": "plan|tool_call|token|complete", "data": ...}
        """
        
        lyricist_text = f" with lyrics by {lyricist}" if lyricist else ""
        
        prompt = f"""You are a music historian creating rich Digital Liner Notes for a CD collection.

CD Details:
- Album: "{album_name}"
- Artist: {artist}
- Lyricist: {lyricist or "Unknown"}
- Genre: {genre}

Your task:
1. First, create a research plan with specific search queries
2. Search for information about:
   - The album's recording history, critical reception, and notable tracks
   - The lyricist's background and songwriting style (if known)
   - Cultural impact and interesting trivia
3. Synthesize a comprehensive markdown report with these sections:
   - **The Album Story** (recording context, production, reception)
   - **Lyricist & Songwriting Spotlight** (if lyricist is known)
   - **Hidden Trivia** (interesting facts)

Do not title the report "Digital Liner Notes" and do not include a sources section.

Be thorough but concise. Focus on verified information."""

        yield {
            "type": "plan",
            "data": {"status": "Planning research strategy..."}
        }
        
        # Simulate research planning
        plan_queries = [
            f"{album_name} {artist} album review history",
            f"{album_name} {artist} recording production",
            f"{lyricist} songwriter style" if lyricist else None,
            f"{artist} {album_name} trivia facts"
        ]
        plan_queries = [q for q in plan_queries if q]
        
        yield {
            "type": "plan",
            "data": {"queries": plan_queries}
        }
        
        # Execute searches via Brave Search API, paced to the Free plan's
        # 1 req/sec limit. Per-query failures are emitted as a non-terminal
        # 'search_error' event so one bad query doesn't tear down the stream
        # on the client (which treats 'error' as fatal and closes the drawer).
        all_results = []
        for idx, query in enumerate(plan_queries):
            if idx > 0:
                await asyncio.sleep(BRAVE_RATE_LIMIT_DELAY_SECONDS)

            yield {
                "type": "tool_call",
                "data": {"tool": "brave_search", "query": query},
            }

            try:
                results = await BraveSearchService.search(
                    query=query, api_key=self.brave_key, count=5
                )
                all_results.extend(results)
            except Exception as e:
                yield {
                    "type": "search_error",
                    "data": {"query": query, "message": f"Brave Search error: {str(e)}"},
                }
        
        synthesis_prompt = f"""Based on the following research results, write liner notes for "{album_name}" by {artist}{lyricist_text}.

Research Results:
{json.dumps(all_results, indent=2)}

Format your response as markdown with these sections:
- **The Album Story**
- **Lyricist & Songwriting Spotlight** (if lyricist info is available)
- **Hidden Trivia**

Do not start with "Digital Liner Notes" and do not include a sources list.

Be engaging and informative."""

        # Stream synthesis
        messages = [HumanMessage(content=synthesis_prompt)]

        full_response = ""
        async for chunk in self.llm.astream(messages):
            text = _extract_text(getattr(chunk, "content", None))
            if not text:
                continue
            full_response += text
            yield {
                "type": "token",
                "data": {"content": text},
            }

        # Newer Claude models can stream only thinking blocks. If we got no
        # visible text, fall back to a non-streaming call so the drawer still
        # receives liner notes instead of sources-only.
        if not full_response.strip():
            result = await self.llm.ainvoke(messages)
            full_response = _extract_text(getattr(result, "content", None))
            if full_response:
                yield {
                    "type": "token",
                    "data": {"content": full_response},
                }
        
        # Extract sources
        sources = []
        for result in all_results:
            if isinstance(result, dict) and "url" in result:
                sources.append({
                    "title": result.get("title", result.get("url", "Source")),
                    "url": result["url"]
                })
        
        yield {
            "type": "complete",
            "data": {
                "summary": full_response,
                "sources": sources[:10]  # Limit to top 10
            }
        }
