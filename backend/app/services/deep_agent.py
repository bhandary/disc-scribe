from typing import AsyncIterator, Dict, Any, Optional
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_community.tools.tavily_search import TavilySearchResults
from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.tools import tool
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from typing_extensions import TypedDict
import json


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
        tavily_key: str,
        anthropic_key: Optional[str] = None,
        openai_key: Optional[str] = None,
        model: str = "claude-haiku-5-5"
    ):
        self.tavily_key = tavily_key
        
        # Initialize LLM based on model. Note: newer Claude models (Haiku 5.5,
        # Opus 4.x+, reasoning-tier Sonnets) reject the `temperature` param, so
        # we omit it and let each model use its own default.
        if "claude" in model.lower() and anthropic_key:
            self.llm = ChatAnthropic(
                model=model,
                anthropic_api_key=anthropic_key,
            )
        elif openai_key:
            self.llm = ChatOpenAI(
                model=model if "gpt" in model.lower() else "gpt-4o",
                openai_api_key=openai_key,
                temperature=0.7,
            )
        else:
            raise ValueError("No valid API key provided for LLM")
        
        self.tavily_tool = TavilySearchResults(
            max_results=5,
            api_key=tavily_key,
            search_depth="advanced"
        )
    
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
   - **Verified Sources** (list of URLs with titles)

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
        
        # Execute searches
        all_results = []
        for query in plan_queries:
            yield {
                "type": "tool_call",
                "data": {"tool": "tavily_search", "query": query}
            }
            
            try:
                results = await self.tavily_tool.ainvoke({"query": query})
                if isinstance(results, list):
                    all_results.extend(results)
                elif isinstance(results, str):
                    all_results.append({"content": results, "url": ""})
            except Exception as e:
                yield {
                    "type": "error",
                    "data": {"message": f"Search error: {str(e)}"}
                }
        
        # Synthesize report
        yield {
            "type": "token",
            "data": {"content": "\n\n# Digital Liner Notes\n\n"}
        }
        
        synthesis_prompt = f"""Based on the following research results, write comprehensive Digital Liner Notes for "{album_name}" by {artist}{lyricist_text}.

Research Results:
{json.dumps(all_results, indent=2)}

Format your response as markdown with these sections:
- **The Album Story**
- **Lyricist & Songwriting Spotlight** (if lyricist info is available)
- **Hidden Trivia**
- **Verified Sources** (as a bullet list with titles and URLs)

Be engaging and informative."""

        # Stream synthesis
        messages = [HumanMessage(content=synthesis_prompt)]
        
        full_response = ""
        async for chunk in self.llm.astream(messages):
            if hasattr(chunk, 'content') and chunk.content:
                full_response += chunk.content
                yield {
                    "type": "token",
                    "data": {"content": chunk.content}
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
