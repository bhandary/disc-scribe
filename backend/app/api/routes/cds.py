from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, Request, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_, literal_column
from sqlalchemy.dialects.postgresql import insert as pg_insert
from typing import List, Optional
from uuid import UUID
import csv
import io
import uuid
from datetime import datetime, timezone
from sse_starlette.sse import EventSourceResponse
import asyncio

from app.core.auth import get_current_user
from app.core.database import AsyncSessionLocal, get_db
from app.models.cd import CD
from app.models.user import User
from app.schemas.cd import CDCreate, CDResponse, CDSearchResponse
from app.services.musicbrainz import MusicBrainzService
from app.services.deep_agent import DeepAgentEnricher
from app.core.config import get_runtime_keys

router = APIRouter(prefix="/api/cds", tags=["cds"])


async def _upsert_cd(
    db: AsyncSession,
    *,
    user_id: UUID,
    artist: str,
    album_name: str,
    lyricist: Optional[str],
    genre: str,
    num_discs: int,
) -> bool:
    """Insert a CD or update the row that shares this user's lowercased artist and album.

    The conflict target is the expression unique index uq_artist_album_lowercase
    on (user_id, LOWER(artist), LOWER(album_name)). Another user's copy of the
    same album is a different key. A duplicate becomes an update of lyricist,
    genre, num_discs, and updated_at. ai_summary, cover art, the stored names,
    and user_id stay as they were. Returns True when this statement stored a
    new row. Postgres sets xmax to 0 only on the insert path of ON CONFLICT DO UPDATE.
    """
    now = datetime.now(timezone.utc)
    stmt = pg_insert(CD).values(
        id=uuid.uuid4(),
        user_id=user_id,
        artist=artist,
        album_name=album_name,
        lyricist=lyricist,
        genre=genre,
        num_discs=num_discs,
        created_at=now,
        updated_at=now,
    )
    excluded = stmt.excluded
    stmt = stmt.on_conflict_do_update(
        index_elements=[
            literal_column("user_id"),
            literal_column("lower(artist)"),
            literal_column("lower(album_name)"),
        ],
        set_={
            "lyricist": excluded.lyricist,
            "genre": excluded.genre,
            "num_discs": excluded.num_discs,
            "updated_at": excluded.updated_at,
        },
    ).returning(literal_column("(xmax = 0)").label("inserted"))
    result = await db.execute(stmt)
    return bool(result.scalar())


@router.post("/upload-csv")
async def upload_csv(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
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
    pending = []
    
    for idx, row in enumerate(csv_reader, start=2):
        try:
            # Handle duplicate 'artist' columns by taking the first non-empty one
            artist = (row.get('artist') or '').strip()
            
            # Map flexible column names. Strip album_name the same way as artist
            # so "Abbey Road" and "Abbey Road " share one catalog key.
            album_name = (row.get('album_name') or row.get('album') or '').strip()
            lyricist = (row.get('lyricist') or '').strip() or None
            genre = (row.get('genre') or '').strip()
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
            
            pending.append((idx, artist, album_name, lyricist, genre, num_discs))
            
        except Exception as e:
            errors.append({
                "row": idx,
                "error": str(e)
            })

    # Same lock order in every request: LOWER(artist), LOWER(album_name).
    # user_id is the same for every row of this upload, so it does not change
    # the order. Two uploads of one user wait on uq_artist_album_lowercase
    # without deadlocking. Another user's album is a different key.
    pending.sort(key=lambda item: (item[1].lower(), item[2].lower()))

    for idx, artist, album_name, lyricist, genre, num_discs in pending:
        try:
            if await _upsert_cd(
                db,
                user_id=user.id,
                artist=artist,
                album_name=album_name,
                lyricist=lyricist,
                genre=genre,
                num_discs=num_discs,
            ):
                inserted += 1
            else:
                updated += 1
        except Exception as e:
            errors.append({
                "row": idx,
                "error": str(e)
            })
    
    await db.commit()
    
    # Trigger background task for cover art (simplified - in production use celery/arq)
    asyncio.create_task(fetch_missing_cover_art(user.id))
    
    return {
        "inserted": inserted,
        "updated": updated,
        "errors": errors
    }


async def fetch_missing_cover_art(user_id: UUID):
    """Background task to fetch missing cover art for one user's shelf."""
    try:
        async with AsyncSessionLocal() as db:
            stmt = (
                select(CD)
                .where(CD.user_id == user_id, CD.cover_art_url.is_(None))
                .limit(50)
            )
            result = await db.execute(stmt)
            cds = result.scalars().all()

            for cd in cds:
                cover_url = await MusicBrainzService.fetch_cover_art(cd.artist, cd.album_name)
                if cover_url:
                    cd.cover_art_url = cover_url
                    await db.commit()
                    await asyncio.sleep(2)  # Rate limiting
    except Exception as e:
        print(f"Cover art fetch error: {e}")


@router.get("/search", response_model=CDSearchResponse)
async def search_cds(
    q: Optional[str] = Query(None, description="Omni-search query"),
    artist: Optional[str] = Query(None),
    album_name: Optional[str] = Query(None),
    lyricist: Optional[str] = Query(None),
    genre: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Multi-field fuzzy search with pg_trgm, limited to the signed-in user's shelf."""
    
    offset = (page - 1) * limit
    
    # Rows with no owner (imported before accounts) stay hidden.
    conditions = [CD.user_id == user.id]
    
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
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Stream AI enrichment via SSE"""
    
    result = await db.execute(select(CD).where(CD.id == cd_id, CD.user_id == user.id))
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
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get single CD by ID, only if it belongs to the signed-in user."""
    result = await db.execute(select(CD).where(CD.id == cd_id, CD.user_id == user.id))
    cd = result.scalar_one_or_none()
    
    if not cd:
        raise HTTPException(status_code=404, detail="CD not found")
    
    return CDResponse(
        **cd.__dict__,
        needs_enrichment=cd.ai_summary is None
    )
