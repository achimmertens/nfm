# Docker Configuration for NFM

This directory contains all Docker-related configuration files for the News Feed Manager application.

## Files

### Dockerfile.amd64
Multi-stage Dockerfile for building the amd64 platform image:
- **Stage 1 (Builder)**: Installs dependencies and preloads the embedding model
- **Stage 2 (Runtime)**: Creates minimal runtime image with cached model

### docker-compose.amd64.yml
Docker Compose configuration defining:
- **nginx**: Reverse proxy and web server (ports 80/443)
- **nfm-app**: FastAPI application (internal port 8000)
- **Volumes**: Configuration, auxiliary data, and clicktrack directories
- **Network**: Bridge network for container communication

### .dockerignore
Specifies files and directories to exclude from the Docker build context.

### build-amd64.cmd
Windows batch script for building and pushing the Docker image to Docker Hub.

## Quick Start

1. **Build the image:**
   ```cmd
   build-amd64.cmd
   ```

2. **Start the application:**
   ```cmd
   docker-compose -f docker-compose.amd64.yml up -d
   ```

3. **Access the application:**
   - Web UI: http://localhost/achim
   - API Docs: http://localhost/docs

## Volume Mappings

The following directories are mounted from the host:

- `../app/conf` → `/app/app/conf` (Configuration files)
- `../aux_data` → `/app/aux_data` (Secrets, stopwords, last run timestamp)
- `../clicktrack` → `/app/clicktrack` (User interaction logs)

## Build Process

The build script performs:
1. Builds Docker image for linux/amd64 platform
2. Tags image as `apollon67/newsreader:latest` and `apollon67/newsreader:amd64`
3. Logs in to Docker Hub
4. Pushes both tags to the registry

## Model Preloading

The Dockerfile preloads the sentence transformer model during build:
- Model: `paraphrase-multilingual-MiniLM-L12-v2`
- Cached in: `/root/.cache/torch/sentence_transformers`
- Size: ~500MB

This eliminates download time on first run.

## Network Architecture

```
Internet → Nginx (Port 80/443) → nfm-app (Port 8000)
```

Nginx handles:
- Reverse proxy to FastAPI application
- Static file serving and caching
- Rate limiting
- Security headers
- Gzip compression

## Documentation

For detailed documentation, see:
- **Comprehensive Guide**: `../doc/DOCKER_DEPLOYMENT.md`
- **Quick Reference**: `../doc/DOCKER_QUICK_REFERENCE.md`

## Configuration

Before running, ensure:
1. `../aux_data/secrets.json` exists with email credentials
2. `../app/conf/config.py` is configured with user settings and feed URLs
3. Required directories exist: `aux_data/`, `clicktrack/`

## Troubleshooting

### Build fails
- Ensure Docker is running
- Check internet connectivity (for downloading packages)
- Verify pyproject.toml is present in parent directory

### Container won't start
```cmd
docker-compose -f docker-compose.amd64.yml logs
```

### Port conflicts
Edit `docker-compose.amd64.yml` and change the nginx port mapping:
```yaml
ports:
  - "8080:80"  # Use port 8080 instead of 80
```

## Support

For issues or questions, refer to the main documentation in the `doc/` directory.
