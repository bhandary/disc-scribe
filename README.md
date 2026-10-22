# The Rack

A full-stack web application to catalog, search, and enrich your physical Music CD collection with AI-powered insights.

![DiscVault AI](https://img.shields.io/badge/Stack-Next.js%20%2B%20FastAPI-blue)
![License](https://img.shields.io/badge/License-MIT-green)

## ✨ Features

- **3D Jewel Case Grid** — Interactive CD collection display with realistic plastic effects
- **Smart Search** — Multi-field fuzzy search with PostgreSQL pg_trgm
- **AI-Powered Enrichment** — Deep Agent generates comprehensive Digital Liner Notes using LangChain + Brave Search
- **CSV Import** — Drag-and-drop bulk upload with automatic deduplication
- **Cover Art Fetching** — Automatic album art from MusicBrainz/Cover Art Archive
- **Encrypted API Keys** — Secure configuration vault using Fernet encryption
- **Beautiful Dark UI** — Inspired by Roon and teenage engineering

## 🏗️ Architecture

### Backend (`/backend`)
- **Framework:** FastAPI + SQLAlchemy 2.0 (asyncpg)
- **Database:** PostgreSQL 16 with `pgvector` and `pg_trgm` extensions
- **AI Stack:** LangChain, LangGraph, Brave Search, Claude/GPT-4o
- **Features:**
  - Dynamic API key resolution (DB → Headers → Env)
  - Server-Sent Events (SSE) streaming for AI enrichment
  - Alembic migrations
  - MusicBrainz integration

### Frontend (`/frontend`)
- **Framework:** Next.js 15 (App Router) + TypeScript
- **Styling:** Tailwind CSS with custom dark theme
- **UI Components:** shadcn/ui + Radix UI primitives
- **Animation:** Framer Motion
- **Features:**
  - Real-time SSE streaming for AI insights
  - Drag-and-drop CSV import with preview
  - API key vault modal
  - Responsive design

## 🚀 Quick Start

### Prerequisites
- Docker & Docker Compose
- Node.js 20+ (for local development)
- Python 3.12+ (for local development)

### One-Command Local Setup

```bash
# Clone the repository
git clone <your-repo-url>
cd discvault-ai

# Copy environment variables
cp .env.example .env

# Start all services
docker-compose up --build
```

The app will be available at:
- **Frontend:** http://localhost:3001
- **Backend API:** http://localhost:8000
- **API Docs:** http://localhost:8000/docs

### Manual Local Development

#### Backend Setup

```bash
cd backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Set up database
docker run -d \
  --name discvault-postgres \
  -e POSTGRES_DB=discvault \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=postgres \
  -p 5432:5432 \
  pgvector/pgvector:pg16

# Run migrations
alembic upgrade head

# Start server
uvicorn app.main:app --reload --port 8000
```

#### Frontend Setup

```bash
cd frontend

# Install dependencies
npm install

# Start dev server
npm run dev
```

Visit http://localhost:3000

## 📊 Database Schema

### `cds` Table
| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID | Primary key |
| `artist` | VARCHAR(255) | Artist name (indexed with pg_trgm) |
| `album_name` | VARCHAR(255) | Album title (indexed with pg_trgm) |
| `lyricist` | VARCHAR(255) | Lyricist/songwriter (optional) |
| `genre` | VARCHAR(100) | Music genre |
| `num_discs` | INTEGER | Number of discs in set |
| `cover_art_url` | TEXT | Album cover image URL |
| `release_year` | INTEGER | Release year |
| `ai_summary` | TEXT | Cached AI-generated liner notes |
| `ai_sources` | JSONB | Verified source citations |
| `embedding` | VECTOR(1536) | For semantic search |
| `created_at` | TIMESTAMP | Record creation timestamp |
| `updated_at` | TIMESTAMP | Last update timestamp |

**Unique Constraint:** `(LOWER(artist), LOWER(album_name))`

### `app_settings` Table
Stores encrypted API keys and configuration.

## 🔧 Configuration

### API Keys (Settings Modal)
1. Click the ⚙️ settings icon in the header
2. Add your API keys:
   - **Brave Search API Key:** For web search (required)
   - **Anthropic API Key:** For Claude models
   - **OpenAI API Key:** For GPT models
3. Select your preferred LLM model

Keys are encrypted with Fernet and stored in the database.

### CSV Import Format

```csv
artist,album_name,lyricist,genre,num_discs
The Beatles,Abbey Road,John Lennon,Rock,1
A.R. Rahman,Dil Se,Gulzar,Bollywood,1
```

Required fields: `artist`, `album_name`, `genre`

## 🎨 UI/UX Highlights

- **Tactile Audiophile Dark Mode** — Deep obsidian (#090A0F) with warm vinyl gold accents
- **Glassmorphic Overlays** — `backdrop-blur-xl` with semi-transparent zinc backgrounds
- **Jewel Case Cards** — Realistic spine ridges and plastic glare effects
- **Smooth Animations** — Spring physics and hover tilts via Framer Motion

## 🚢 Deployment

### Railway (Backend)
```bash
cd backend
railway up
```

Configure environment variables in Railway dashboard.

### Vercel (Frontend)
```bash
cd frontend
vercel
```

Set `NEXT_PUBLIC_API_URL` to your Railway backend URL.

## 🧪 Development Tools

- **API Documentation:** http://localhost:8000/docs (Swagger UI)
- **Alembic Migrations:** `alembic revision --autogenerate -m "message"`
- **Type Checking:** `mypy app/`
- **Linting:** `eslint . --ext ts,tsx` (frontend)

## 📝 License

MIT

## 🙏 Acknowledgments

- **MusicBrainz** for album metadata
- **Cover Art Archive** for album artwork
- **Brave Search** for web search API
- **shadcn/ui** for beautiful components
- **LangChain** for AI orchestration

---

Built with ❤️ for music collectors and AI enthusiasts.
