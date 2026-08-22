# News Feed Manager (NFM) - Docker Deployment Guide

## Table of Contents
1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Prerequisites](#prerequisites)
4. [Quick Start](#quick-start)
5. [Configuration](#configuration)
6. [Building the Image](#building-the-image)
7. [Running the Application](#running-the-application)
8. [Volume Mappings](#volume-mappings)
9. [Nginx Configuration](#nginx-configuration)
10. [Maintenance](#maintenance)
11. [Troubleshooting](#troubleshooting)
12. [Security Considerations](#security-considerations)

---

## Overview

The News Feed Manager (NFM) is a containerized FastAPI application that aggregates news from multiple RSS feeds, performs semantic deduplication, and delivers personalized news summaries via email.

### Key Features
- Multi-source RSS feed aggregation
- Semantic deduplication using sentence transformers
- Scheduled email delivery
- Web interface for news browsing
- Click tracking and rating system
- Configurable per-user settings

---

## Architecture

The application consists of two Docker containers:

1. **nfm-app**: FastAPI application (Python 3.11)
   - Runs on port 8000 (internal)
   - Handles feed processing, deduplication, and rendering
   - Scheduled tasks for updates and email delivery

2. **nginx**: Reverse proxy and web server
   - Exposes ports 80 (HTTP) and 443 (HTTPS)
   - Handles static file serving and caching
   - Rate limiting for API endpoints
   - Security headers

### Container Communication
- Both containers run on the `nfm-network` bridge network
- Nginx proxies requests to `nfm-app:8000`
- Health checks ensure container availability

---

## Prerequisites

### Required Software
- Docker Engine 20.10 or later
- Docker Compose 2.0 or later
- 4GB RAM minimum (8GB recommended)
- 10GB free disk space

### Windows System Requirements
- Windows 10 version 2004 or later, or Windows 11
- WSL 2 (Windows Subsystem for Linux) enabled
- Docker Desktop for Windows

### Platform
- Target platform: `linux/amd64`
- Built and tested on Windows with Docker Desktop

---

## Quick Start

### 1. Clone or Navigate to Project Directory
```cmd
cd "g:\Meine Ablage\_projects\2025\251121 - newsreader"
```

### 2. Configure Secrets
Create or update `secrets/secrets.json`:
```json
{
  "email": {
    "smtp_server": "smtp.gmail.com",
    "smtp_port": 587,
    "sender_email": "your-email@gmail.com",
    "sender_password": "your-app-password"
  }
}
```

### 3. Build and Run
```cmd
cd docker
docker-compose -f docker-compose.amd64.yml up -d
```

### 4. Verify Deployment
```cmd
docker-compose -f docker-compose.amd64.yml ps
```

Access the application:
- Web UI: http://localhost/achim
- API Docs: http://localhost/docs

---

## Configuration

### Application Configuration

The main configuration is in `app/conf/config.py`:

#### User Settings
```python
config_achim = {
    "settings": {
        "uid": "achim",                           # User ID
        "recipients": ["user@example.com"],       # Email recipients
        "source_sort_order": {...},               # Feed source priority
        "blacklist_link": [...],                  # URL patterns to exclude
        "blacklist_title": [...],                 # Title keywords to exclude
        "highlight_keywords": [...],              # Keywords to highlight
    },
    "feeds": [
        {
            "source": "Tagesschau",               # Feed source name
            "url": "https://...",                 # RSS feed URL
            "topic": "Politik",                   # Topic category
            "check_paywall": False                # Optional: Check for paywall
        },
        # ... more feeds
    ]
}
```

#### Application Parameters
- `LIMIT`: Number of articles per feed (default: 4)
- `HOURS_BACK`: Time window for articles (default: 24)
- `SECRETS_FILE`: Path to secrets configuration

### Scheduled Tasks

Configured in `main.py`:

1. **Update Render Data**: Hourly
   - Fetches and processes feeds
   - Updates article cache
   - Performs deduplication

2. **Send Email**: Daily at 05:55 (configurable via `CRONTRIGGER` in config.py)
   - Generates email summary
   - Sends to configured recipients

---

## Building the Image

### Build Script (Windows)

The `build-amd64.cmd` script automates building and pushing:

```cmd
cd docker
build-amd64.cmd
```

### Manual Build

```cmd
cd "g:\Meine Ablage\_projects\2025\251121 - newsreader"

docker build ^
    --platform linux/amd64 ^
    --file docker\Dockerfile.amd64 ^
    --tag apollon67/newsreader:latest ^
    --tag apollon67/newsreader:amd64 ^
    .
```

### Build Process

The Dockerfile uses multi-stage builds:

**Stage 1: Builder**
- Installs build dependencies (gcc, g++)
- Installs Python packages from `pyproject.toml`
- **Preloads embedding model** (`paraphrase-multilingual-MiniLM-L12-v2`)
- Caches model in `/root/.cache`

**Stage 2: Runtime**
- Minimal Python 3.11 slim image
- Copies installed packages and model cache
- Copies application code
- Sets up directory structure

### Push to Docker Hub

```cmd
docker login
docker push apollon67/newsreader:latest
docker push apollon67/newsreader:amd64
```

---

## Running the Application

### Start Services
```cmd
cd docker
docker-compose -f docker-compose.amd64.yml up -d
```

### Stop Services
```cmd
docker-compose -f docker-compose.amd64.yml down
```

### Restart Services
```cmd
docker-compose -f docker-compose.amd64.yml restart
```

### View Logs
```cmd
# All services
docker-compose -f docker-compose.amd64.yml logs -f

# Specific service
docker-compose -f docker-compose.amd64.yml logs -f nfm-app
docker-compose -f docker-compose.amd64.yml logs -f nginx
```

### Update to Latest Image
```cmd
docker-compose -f docker-compose.amd64.yml pull
docker-compose -f docker-compose.amd64.yml up -d
```

---

## Volume Mappings

Three directories are mounted as volumes for persistent data:

### Configuration Files
```yaml
# Individual configuration files mounted
C:/_docker/nfm/conf/config.py -> /app/app/conf/config.py
C:/_docker/nfm/conf/logging_config.py -> /app/app/conf/logging_config.py
```
**Contains:**
- `config.py`: User configurations and feed URLs
- `logging_config.py`: Logging settings

**Note:** Configuration files are mounted individually to preserve Python package structure.

**Permissions:** Read/Write

### 2. Secrets Directory
```yaml
C:/_docker/nfm/secrets -> /app/secrets
```
**Contains:**
- `secrets.json`: Email credentials (sensitive!)

**Note:** `german_stopwords.json` is baked into the Docker image at `/app/aux_data/german_stopwords.json`

**Permissions:** Read/Write

### 3. Click Tracking Directory
```yaml
C:/_docker/nfm/clicktrack -> /app/clicktrack
```
**Contains:**
- `clicktrack_{uid}.jsonl`: User interaction logs
- Records article clicks and ratings

**Permissions:** Read/Write

### Security Note
⚠️ **NEVER commit `secrets/secrets.json` to version control!**

---

## Nginx Configuration

### Configuration File Location
```
nginx/conf/nginx.conf
```

### Key Features

#### 1. Upstream Backend
```nginx
upstream nfm_backend {
    server nfm-app:8000;
    keepalive 32;
}
```

#### 2. Static File Caching
```nginx
location /static/ {
    expires 1y;
    add_header Cache-Control "public, immutable";
}
```

#### 3. Rate Limiting
```nginx
limit_req_zone $binary_remote_addr zone=api_limit:10m rate=10r/s;

location ~ ^/(send_email|clicktrack) {
    limit_req zone=api_limit burst=5 nodelay;
}
```

#### 4. Security Headers
- `X-Frame-Options: SAMEORIGIN`
- `X-Content-Type-Options: nosniff`
- `X-XSS-Protection: 1; mode=block`
- `Referrer-Policy: no-referrer-when-downgrade`

#### 5. Compression
- Gzip enabled for text and JSON responses
- Compression level: 6

### Custom Configuration

To modify nginx settings:

1. Edit `nginx/conf/nginx.conf` locally
2. Update the mounted configuration (deployment-specific path)
3. Restart nginx container:
   ```cmd
   docker-compose -f docker-compose.amd64.yml restart nginx
   ```

---

## Maintenance

### Health Checks

Both containers include health checks:

```yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:8000/docs"]
  interval: 30s
  timeout: 10s
  retries: 3
  start_period: 60s
```

Monitor health:
```cmd
docker inspect --format='{{.State.Health.Status}}' nfm-app
```

### Database/Cache Cleanup

The application uses in-memory caching. To reset:
```cmd
# Remove render data cache
del "render_data_*.json"

# Restart application
docker-compose -f docker-compose.amd64.yml restart nfm-app
```

### Log Rotation

Nginx logs are stored in a named volume `nginx_logs`.

Access logs:
```cmd
docker exec -it nfm-nginx cat /var/log/nginx/access.log
```

Clear logs:
```cmd
docker exec -it nfm-nginx sh -c "echo '' > /var/log/nginx/access.log"
docker exec -it nfm-nginx sh -c "echo '' > /var/log/nginx/error.log"
```

### Backup

**Important files to backup:**
```cmd
# Configuration
app\conf\config.py
app\conf\logging_config.py

# Nginx configuration
nginx\conf\nginx.conf

# Secrets
secrets\secrets.json

# Click tracking data
clicktrack\clicktrack_*.jsonl

# Auxiliary data (baked into image, backup source)
aux_data\german_stopwords.json
```

**Backup command:**
```cmd
xcopy /E /I /Y "app\conf" "backup\app\conf"
xcopy /E /I /Y "nginx\conf" "backup\nginx\conf"
xcopy /E /I /Y "secrets" "backup\secrets"
xcopy /E /I /Y "clicktrack" "backup\clicktrack"
xcopy /E /I /Y "aux_data" "backup\aux_data"
```

---

## Troubleshooting

### Container Won't Start

**Check logs:**
```cmd
docker-compose -f docker-compose.amd64.yml logs nfm-app
```

**Common issues:**
1. Port 80/443 already in use
   - Solution: Stop other web servers or change ports in `docker-compose.amd64.yml`

2. Missing secrets file
   - Solution: Create `aux_data/secrets.json`

3. Volume mount permissions
   - Solution: Ensure directories exist and are accessible

### Application Not Responding

**Check container status:**
```cmd
docker-compose -f docker-compose.amd64.yml ps
```

**Restart application:**
```cmd
docker-compose -f docker-compose.amd64.yml restart nfm-app
```

**Check health:**
```cmd
curl http://localhost/docs
```

### Email Not Sending

**Verify configuration:**
1. Check `aux_data/secrets.json` for correct credentials
2. For Gmail: Use App Password, not account password
3. Enable "Less secure app access" or use OAuth2

**Test email manually:**
```cmd
curl http://localhost/send_email/achim
```

### Model Loading Issues

If the embedding model fails to load:

1. **Rebuild image to re-download model:**
   ```cmd
   docker-compose -f docker-compose.amd64.yml build --no-cache
   ```

2. **Check model cache:**
   ```cmd
   docker exec -it nfm-app ls -la /root/.cache/torch/sentence_transformers
   ```

### High Memory Usage

The embedding model requires ~500MB RAM.

**Monitor usage:**
```cmd
docker stats nfm-app
```

**Increase Docker memory limit:**
Docker Desktop → Settings → Resources → Memory: 4GB minimum

### Network Issues

**Test container connectivity:**
```cmd
docker exec -it nfm-nginx ping nfm-app
```

**Verify network:**
```cmd
docker network inspect docker_nfm-network
```

---

## Security Considerations

### Secrets Management

1. **Never commit secrets to git:**
   ```gitignore
   secrets/secrets.json
   ```

2. **Use environment variables (alternative):**
   ```yaml
   environment:
     - SMTP_SERVER=${SMTP_SERVER}
     - SMTP_PASSWORD=${SMTP_PASSWORD}
   ```

3. **File permissions:**
   ```cmd
   # On deployment server:
   chmod 600 secrets/secrets.json
   ```

### Network Security

1. **Use HTTPS in production:**
   - Add SSL certificates to nginx
   - Update nginx.conf with SSL configuration
   - Redirect HTTP to HTTPS

2. **Firewall configuration:**
   - Only expose port 443 externally
   - Keep port 8000 internal

### Container Security

1. **Run as non-root user (future enhancement):**
   ```dockerfile
   USER appuser
   ```

2. **Read-only filesystem:**
   ```yaml
   read_only: true
   ```

3. **Security scanning:**
   ```cmd
   docker scout quickview apollon67/newsreader:latest
   ```

### Rate Limiting

Nginx includes rate limiting:
- 10 requests/second per IP
- Burst of 5 additional requests
- 429 status for exceeded limits

### Updates

**Regularly update base images:**
```cmd
docker pull python:3.11-slim
docker pull nginx:alpine
```

**Rebuild application:**
```cmd
cd docker
build-amd64.cmd
```

---

## Advanced Topics

### Multi-User Configuration

To add additional users:

1. **Edit `app/conf/config.py`:**
   ```python
   user_cfgs = [config_achim, config_sonja]
   ```

2. **Create clicktrack directory:**
   ```cmd
   mkdir clicktrack
   ```

3. **Restart application:**
   ```cmd
   docker-compose -f docker-compose.amd64.yml restart nfm-app
   ```

4. **Access user feeds:**
   - User 1: http://localhost/achim
   - User 2: http://localhost/sonja

### Custom Scheduling

Edit `main.py` to modify schedule:

```python
# Update every 30 minutes instead of hourly
scheduler.add_job(
    update_render_data,
    trigger=IntervalTrigger(minutes=30),
    ...
)

# Send email at 08:00 instead of 06:00
scheduler.add_job(
    send_app_via_email,
    trigger=CronTrigger(hour=8, minute=0),
    ...
)
```

### Monitoring

**Prometheus metrics (future enhancement):**
- Add `prometheus-fastapi-instrumentator`
- Expose `/metrics` endpoint
- Configure Prometheus scraping

**Grafana dashboard:**
- Feed update frequency
- Deduplication statistics
- Email delivery status
- API response times

---

## Support and Resources

### Documentation
- FastAPI: https://fastapi.tiangolo.com/
- Sentence Transformers: https://www.sbert.net/
- Docker: https://docs.docker.com/
- Nginx: https://nginx.org/en/docs/

### Project Structure
```
newsreader/
├── app/
│   ├── conf/          # Configuration files
│   ├── core/          # Core business logic
│   └── web/           # Web interface (templates, static)
├── aux_data/          # Auxiliary data (secrets, stopwords)
├── clicktrack/        # User interaction logs
├── docker/            # Docker configuration
│   ├── .dockerignore
│   ├── Dockerfile.amd64
│   ├── docker-compose.amd64.yml
│   └── build-amd64.cmd
├── doc/               # Documentation
├── main.py            # Application entry point
└── pyproject.toml     # Python dependencies
```

---

## Changelog

### Version 1.0.0 (2025-11-23)
- Initial containerized release
- Multi-stage Docker build
- Nginx reverse proxy
- Preloaded embedding model
- Volume mappings for configuration and data
- Automated build script
- Comprehensive documentation

---

## License

[Your License Here]

---

## Contact

For issues or questions, please contact the development team.
