from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, Request, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_
from typing import List, Optional
from uuid import UUID
import csv
import io
from sse_starlette.sse import EventSourceResponse
import asyncio
import json

from app.core.database import get_db, AsyncSessionLocal
from app.models.cd import CD
from app.schemas.cd import (
    CDCreate,
    CDResponse,
    CDSearchResponse,
    BarcodeLookupRequest,
    BarcodeLookupResponse,
)
from app.services.musicbrainz import MusicBrainzService
from app.services.barcode import BarcodeLookupService
from app.services.deep_agent import DeepAgentEnricher
from app.core.config import get_runtime_keys

router = APIRouter(prefix="/api/cds", tags=["cds"])


def _to_response(cd: CD) -> CDResponse:
    return CDResponse(
        id=cd.id,
        artist=cd.artist,
        album_name=cd.album_name,
        lyricist=cd.lyricist,
        genre=cd.genre,
        num_discs=cd.num_discs,
        cover_art_url=cd.cover_art_url,
        release_year=cd.release_year,
        barcode=cd.barcode,
        label=cd.label,
        tracks=cd.tracks,
        ai_summary=cd.ai_summary,
        ai_sources=cd.ai_sources,
        created_at=cd.created_at,
        updated_at=cd.updated_at,
        needs_enrichment=cd.ai_summary is None,
    )


async def _find_existing(
    db: AsyncSession,
    *,
    barcode: Optional[str] = None,
    artist: Optional[str] = None,
    album_name: Optional[str] = None,
) -> Optional[CD]:
    if barcode:
        result = await db.execute(select(CD).where(CD.barcode == barcode))
        existing = result.scalar_one_or_none()
        if existing:
            return existing
    if artist and album_name:
        result = await db.execute(
            select(CD).where(
                func.lower(CD.artist) == artist.lower(),
                func.lower(CD.album_name) == album_name.lower(),
            )
        )
        return result.scalar_one_or_none()
    return None


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


@router.get("/facets")
async def get_facets(
    field: str = Query(..., description="artist | album_name | lyricist | genre"),
    db: AsyncSession = Depends(get_db),
):
    """Return unique values (and counts) for a CD field so the UI can filter."""
    field_map = {
        "artist": CD.artist,
        "album": CD.album_name,
        "album_name": CD.album_name,
        "lyricist": CD.lyricist,
        "genre": CD.genre,
    }
    column = field_map.get(field)
    if column is None:
        raise HTTPException(status_code=400, detail="Invalid facet field")

    stmt = (
        select(column.label("value"), func.count().label("count"))
        .where(column.is_not(None))
        .where(func.trim(column) != "")
        .group_by(column)
        .order_by(func.count().desc(), column.asc())
    )
    rows = (await db.execute(stmt)).all()
    return {
        "field": field,
        "values": [{"value": row.value, "count": row.count} for row in rows],
    }


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
                CD.genre.ilike(q_lower),
                CD.barcode.ilike(q_lower),
                CD.label.ilike(q_lower),
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
    
    # Query with conditions. Always order so pagination is stable.
    if conditions:
        stmt = select(CD).where(*conditions).order_by(CD.album_name, CD.artist)
        count_stmt = select(func.count()).select_from(CD).where(*conditions)
    else:
        stmt = select(CD).order_by(CD.album_name, CD.artist)
        count_stmt = select(func.count()).select_from(CD)
    stmt = stmt.offset(offset).limit(limit)
    
    result = await db.execute(stmt)
    cds = result.scalars().all()
    
    count_result = await db.execute(count_stmt)
    total = count_result.scalar()
    
    cd_responses = [_to_response(cd) for cd in cds]
    needs_enrichment_count = sum(1 for cd in cds if cd.ai_summary is None)

    return CDSearchResponse(
        cds=cd_responses,
        total=total,
        page=page,
        limit=limit,
        needs_enrichment_count=needs_enrichment_count
    )


@router.get("/lookup-barcode", response_model=BarcodeLookupResponse)
async def lookup_barcode(
    barcode: str = Query(..., min_length=8, max_length=32),
    db: AsyncSession = Depends(get_db),
):
    """Resolve a CD barcode via MusicBrainz, then Discogs."""
    normalized = BarcodeLookupService.normalize(barcode)
    if len(normalized) < 8:
        raise HTTPException(status_code=400, detail="Barcode must contain at least 8 digits")

    match = await BarcodeLookupService.lookup(normalized)
    if not match:
        raise HTTPException(status_code=404, detail="No album found for that barcode")

    existing = await _find_existing(
        db,
        barcode=match.barcode,
        artist=match.artist,
        album_name=match.album_name,
    )
    return BarcodeLookupResponse(
        barcode=match.barcode,
        artist=match.artist,
        album_name=match.album_name,
        lyricist=match.lyricist,
        genre=match.genre,
        num_discs=match.num_discs,
        cover_art_url=match.cover_art_url,
        release_year=match.release_year,
        label=match.label,
        tracks=match.tracks,
        source=match.source,
        already_in_collection=existing is not None,
        existing_id=existing.id if existing else None,
    )


@router.post("/from-barcode", response_model=CDResponse)
async def add_from_barcode(
    body: BarcodeLookupRequest,
    db: AsyncSession = Depends(get_db),
):
    """Look up a barcode and add the album to the collection."""
    normalized = BarcodeLookupService.normalize(body.barcode)
    if len(normalized) < 8:
        raise HTTPException(status_code=400, detail="Barcode must contain at least 8 digits")

    match = await BarcodeLookupService.lookup(normalized)
    if not match:
        raise HTTPException(status_code=404, detail="No album found for that barcode")

    existing = await _find_existing(
        db,
        barcode=match.barcode,
        artist=match.artist,
        album_name=match.album_name,
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail={"message": "Already in your collection", "id": str(existing.id)},
        )

    cd = CD(
        artist=match.artist,
        album_name=match.album_name,
        lyricist=match.lyricist,
        genre=match.genre,
        num_discs=match.num_discs,
        cover_art_url=match.cover_art_url,
        release_year=match.release_year,
        barcode=match.barcode,
        label=match.label,
        tracks=match.tracks or None,
    )
    db.add(cd)
    await db.commit()
    await db.refresh(cd)

    if not cd.cover_art_url:
        asyncio.create_task(fetch_missing_cover_art(limit=1))

    return _to_response(cd)


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
    
    if not keys["brave"]:
        raise HTTPException(status_code=400, detail="Brave Search API key not configured")
    
    if not keys["anthropic"] and not keys["openai"]:
        raise HTTPException(status_code=400, detail="LLM API key not configured")
    
    async def event_generator():
        try:
            # Initialize Deep Agent
            enricher = DeepAgentEnricher(
                brave_key=keys["brave"],
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
                    # Save to database, but only if we actually got a usable
                    # summary. Caching an empty/truncated summary would make
                    # the drawer render blank forever on next open since the
                    # frontend treats a non-null ai_summary as "done".
                    summary = (event_data.get("summary") or "").strip()
                    if summary:
                        cd.ai_summary = summary
                        cd.ai_sources = event_data.get("sources", [])
                        await db.commit()
                
                # SSE 'data' MUST be a string; passing a dict makes sse-starlette
                # fall back to str(dict) which emits Python repr (single quotes)
                # that JSON.parse chokes on in the browser.
                yield {
                    "event": event_type,
                    "data": json.dumps(event_data, default=str),
                }

        except Exception as e:
            yield {
                "event": "error",
                "data": json.dumps({"message": str(e)}),
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
    
    return _to_response(cd)


@router.delete("/{cd_id}", status_code=204)
async def delete_cd(
    cd_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Remove a CD from the collection."""
    result = await db.execute(select(CD).where(CD.id == cd_id))
    cd = result.scalar_one_or_none()
    if not cd:
        raise HTTPException(status_code=404, detail="CD not found")

    await db.delete(cd)
    await db.commit()
