from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, Request, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_
from typing import List, Optional
from uuid import UUID
import csv
import io
from sse_starlette.sse import EventSourceResponse
import asyncio

from app.core.database import get_db, AsyncSessionLocal
from app.models.cd import CD
from app.schemas.cd import CDCreate, CDResponse, CDSearchResponse
from app.services.musicbrainz import MusicBrainzService
from app.services.deep_agent import DeepAgentEnricher
from app.core.config import get_runtime_keys

router = APIRouter(prefix="/api/cds", tags=["cds"])


@router.post("/upload-csv")
async def upload_csv(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db)
):
    """Upload and process CSV file with CD data"""
    
    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="File must be a CSV")
    
    content = await file.read()
    csv_text = content.decode('utf-8-sig')
    csv_reader = csv.DictReader(io.StringIO(csv_text))
    
    # Normalize headers (case-insensitive)
    if csv_reader.fieldnames:
        normalized_fieldnames = [field.strip().lower() for field in csv_reader.fieldnames]
        csv_reader.fieldnames = normalized_fieldnames
    
    inserted = 0
    updated = 0
    errors = []
    
    for idx, row in enumerate(csv_reader, start=2):
        try:
            # Handle duplicate 'artist' columns by taking the first non-empty one
            artist = row.get('artist', '').strip()
            
            # Map flexible column names
            album_name = row.get('album_name') or row.get('album', '').strip()
            lyricist = row.get('lyricist', '').strip() or None
            genre = row.get('genre', '').strip()
            num_discs_raw = row.get('num_discs') or row.get('discs', '1')
            
            if not artist or not album_name or not genre:
                errors.append({
                    "row": idx,
                    "error": "Missing required fields (artist, album_name, genre)"
                })
                continue
            
            try:
                num_discs = int(num_discs_raw)
                if num_discs < 1:
                    num_discs = 1
            except ValueError:
                num_discs = 1
            
            # Check for existing CD
            stmt = select(CD).where(
                func.lower(CD.artist) == artist.lower(),
                func.lower(CD.album_name) == album_name.lower()
            )
            result = await db.execute(stmt)
            existing_cd = result.scalar_one_or_none()
            
            if existing_cd:
                # Update
                existing_cd.lyricist = lyricist
                existing_cd.genre = genre
                existing_cd.num_discs = num_discs
                updated += 1
            else:
                # Insert
                new_cd = CD(
                    artist=artist,
                    album_name=album_name,
                    lyricist=lyricist,
                    genre=genre,
                    num_discs=num_discs
                )
                db.add(new_cd)
                inserted += 1
            
        except Exception as e:
            errors.append({
                "row": idx,
                "error": str(e)
            })
    
    await db.commit()

    # Fire-and-forget cover-art fetch using its OWN session, so it survives
    # request teardown and backend reloads cancel it cleanly.
    asyncio.create_task(fetch_missing_cover_art(limit=None))

    return {
        "inserted": inserted,
        "updated": updated,
        "errors": errors
    }


@router.post("/refresh-covers")
async def refresh_covers(
    limit: Optional[int] = Query(None, ge=1, le=1000, description="Max CDs to process (default: all missing)"),
    background: bool = Query(True, description="Run in background (returns immediately) vs inline"),
):
    """
    Manually (re)trigger cover-art fetching for all CDs whose cover_art_url IS NULL.
    By default runs in the background and returns immediately with the count queued.
    Set background=false to wait for completion and get a precise fetched count.
    """
    async with AsyncSessionLocal() as session:
        stmt = select(func.count()).select_from(CD).where(CD.cover_art_url.is_(None))
        pending = (await session.execute(stmt)).scalar_one()

    if pending == 0:
        return {"pending": 0, "message": "All CDs already have cover art"}

    to_process = pending if limit is None else min(limit, pending)

    if background:
        asyncio.create_task(fetch_missing_cover_art(limit=limit))
        return {"pending": pending, "queued": to_process, "mode": "background"}

    fetched = await fetch_missing_cover_art(limit=limit)
    return {"pending": pending, "queued": to_process, "fetched": fetched, "mode": "inline"}


async def fetch_missing_cover_art(limit: Optional[int] = None) -> int:
    """
    Background worker: fetches cover art for CDs where cover_art_url IS NULL.
    Uses its OWN AsyncSession (not a request-scoped one) so it survives request
    teardown. Commits per-CD so partial progress persists if the task is cancelled.
    Returns the number of covers successfully fetched.
    """
    fetched = 0
    try:
        async with AsyncSessionLocal() as session:
            stmt = select(CD).where(CD.cover_art_url.is_(None)).order_by(CD.created_at)
            if limit is not None:
                stmt = stmt.limit(limit)
            cds = (await session.execute(stmt)).scalars().all()

            for cd in cds:
                try:
                    cover_url = await MusicBrainzService.fetch_cover_art(cd.artist, cd.album_name)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    print(f"Cover fetch unexpected error for {cd.artist} - {cd.album_name}: {type(e).__name__}: {e}")
                    cover_url = None

                if cover_url:
                    cd.cover_art_url = cover_url
                    await session.commit()
                    fetched += 1
                # MusicBrainzService already sleeps between its own calls; this is
                # extra breathing room between CDs to stay well under rate limits.
                await asyncio.sleep(0.5)
    except asyncio.CancelledError:
        print(f"fetch_missing_cover_art cancelled after {fetched} covers")
        raise
    except Exception as e:
        print(f"fetch_missing_cover_art fatal error after {fetched} covers: {type(e).__name__}: {e}")
    return fetched


@router.get("/search", response_model=CDSearchResponse)
async def search_cds(
    q: Optional[str] = Query(None, description="Omni-search query"),
    artist: Optional[str] = Query(None),
    album_name: Optional[str] = Query(None),
    lyricist: Optional[str] = Query(None),
    genre: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db)
):
    """Multi-field fuzzy search with pg_trgm"""
    
    offset = (page - 1) * limit
    
    # Build query
    conditions = []
    
    if q:
        # Omni-search across all fields
        q_lower = f"%{q.lower()}%"
        conditions.append(
            or_(
                CD.artist.ilike(q_lower),
                CD.album_name.ilike(q_lower),
                CD.lyricist.ilike(q_lower),
                CD.genre.ilike(q_lower)
            )
        )
    
    if artist:
        conditions.append(CD.artist.ilike(f"%{artist}%"))
    if album_name:
        conditions.append(CD.album_name.ilike(f"%{album_name}%"))
    if lyricist:
        conditions.append(CD.lyricist.ilike(f"%{lyricist}%"))
    if genre:
        conditions.append(CD.genre.ilike(f"%{genre}%"))
    
    # Query with conditions
    if conditions:
        stmt = select(CD).where(*conditions).offset(offset).limit(limit)
        count_stmt = select(func.count()).select_from(CD).where(*conditions)
    else:
        stmt = select(CD).offset(offset).limit(limit)
        count_stmt = select(func.count()).select_from(CD)
    
    result = await db.execute(stmt)
    cds = result.scalars().all()
    
    count_result = await db.execute(count_stmt)
    total = count_result.scalar()
    
    # Convert to response models
    cd_responses = []
    needs_enrichment_count = 0
    
    for cd in cds:
        cd_dict = {
            "id": cd.id,
            "artist": cd.artist,
            "album_name": cd.album_name,
            "lyricist": cd.lyricist,
            "genre": cd.genre,
            "num_discs": cd.num_discs,
            "cover_art_url": cd.cover_art_url,
            "release_year": cd.release_year,
            "ai_summary": cd.ai_summary,
            "ai_sources": cd.ai_sources,
            "created_at": cd.created_at,
            "updated_at": cd.updated_at,
            "needs_enrichment": cd.ai_summary is None
        }
        
        if cd.ai_summary is None:
            needs_enrichment_count += 1
        
        cd_responses.append(CDResponse(**cd_dict))
    
    return CDSearchResponse(
        cds=cd_responses,
        total=total,
        page=page,
        limit=limit,
        needs_enrichment_count=needs_enrichment_count
    )


@router.get("/{cd_id}/enrich-stream")
async def enrich_cd_stream(
    cd_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Stream AI enrichment via SSE"""
    
    # Fetch CD
    result = await db.execute(select(CD).where(CD.id == cd_id))
    cd = result.scalar_one_or_none()
    
    if not cd:
        raise HTTPException(status_code=404, detail="CD not found")
    
    # Get runtime keys
    headers = dict(request.headers)
    keys = await get_runtime_keys(db, headers)
    
    if not keys["tavily"]:
        raise HTTPException(status_code=400, detail="Tavily API key not configured")
    
    if not keys["anthropic"] and not keys["openai"]:
        raise HTTPException(status_code=400, detail="LLM API key not configured")
    
    async def event_generator():
        try:
            # Initialize Deep Agent
            enricher = DeepAgentEnricher(
                tavily_key=keys["tavily"],
                anthropic_key=keys["anthropic"],
                openai_key=keys["openai"],
                model=keys["llm_model"]
            )
            
            # Stream enrichment
            async for event in enricher.enrich_cd_stream(
                artist=cd.artist,
                album_name=cd.album_name,
                lyricist=cd.lyricist,
                genre=cd.genre
            ):
                event_type = event.get("type", "message")
                event_data = event.get("data", {})
                
                if event_type == "complete":
                    # Save to database
                    cd.ai_summary = event_data.get("summary")
                    cd.ai_sources = event_data.get("sources", [])
                    await db.commit()
                
                yield {
                    "event": event_type,
                    "data": event_data
                }
        
        except Exception as e:
            yield {
                "event": "error",
                "data": {"message": str(e)}
            }
    
    return EventSourceResponse(event_generator())


@router.get("/{cd_id}", response_model=CDResponse)
async def get_cd(
    cd_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Get single CD by ID"""
    result = await db.execute(select(CD).where(CD.id == cd_id))
    cd = result.scalar_one_or_none()
    
    if not cd:
        raise HTTPException(status_code=404, detail="CD not found")
    
    return CDResponse(
        **cd.__dict__,
        needs_enrichment=cd.ai_summary is None
    )
