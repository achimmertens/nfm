# NFM Docker Quick Reference

## Quick Commands

### Build and Deploy
```cmd
# Build and push to Docker Hub
cd docker
build-amd64.cmd

# Start services
docker-compose -f docker-compose.amd64.yml up -d

# Stop services
docker-compose -f docker-compose.amd64.yml down

# Restart services
docker-compose -f docker-compose.amd64.yml restart

# View logs
docker-compose -f docker-compose.amd64.yml logs -f
```

### Access Points
- Web UI: http://localhost/achim
- API Docs: http://localhost/docs
- Send Email: http://localhost/send_email/achim
- Click Tracking: http://localhost/achim/clicktrack?lid=LINK_ID&rating=RATING

### Status Checks
```cmd
# Container status
docker-compose -f docker-compose.amd64.yml ps

# Container logs
docker-compose -f docker-compose.amd64.yml logs -f nfm-app
docker-compose -f docker-compose.amd64.yml logs -f nginx

# Health check
docker inspect --format='{{.State.Health.Status}}' nfm-app

# Resource usage
docker stats nfm-app
```

### Maintenance
```cmd
# Update to latest image
docker-compose -f docker-compose.amd64.yml pull
docker-compose -f docker-compose.amd64.yml up -d

# Restart after config changes
docker-compose -f docker-compose.amd64.yml restart nfm-app

# Clear logs
docker exec -it nfm-nginx sh -c "echo '' > /var/log/nginx/access.log"
```

## File Locations

### Configuration
- **Application**: `app/conf/config.py`
- **Nginx**: `nginx/conf/nginx.conf`
- **Logging**: `app/conf/logging_config.py`

### Data
- **Secrets**: `secrets/secrets.json`
- **Stopwords**: `aux_data/german_stopwords.json` (baked into Docker image)
- **Click Tracking**: `clicktrack/clicktrack_{uid}.jsonl`

### Docker
- **Dockerfile**: `docker/Dockerfile.amd64`
- **Compose**: `docker/docker-compose.amd64.yml`
- **Ignore**: `docker/.dockerignore`
- **Build Script**: `docker/build-amd64.cmd`

## Troubleshooting

### Container won't start
```cmd
docker-compose -f docker-compose.amd64.yml logs nfm-app
```

### Port already in use
Edit `docker-compose.amd64.yml` and change port 80 to another port:
```yaml
ports:
  - "8080:80"  # Change 80 to 8080 or any free port
```

### Email not sending
1. Check `secrets/secrets.json` credentials
2. For Gmail: Use App Password
3. Test manually: `curl http://localhost/send_email/achim`

### Model loading issues
```cmd
# Rebuild without cache
docker-compose -f docker-compose.amd64.yml build --no-cache
docker-compose -f docker-compose.amd64.yml up -d
```

### High memory usage
Docker Desktop → Settings → Resources → Memory: Set to 4GB minimum

## Configuration Examples

### secrets.json
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

### Adding a new user
In `app/conf/config.py`:
```python
user_cfgs = [config_achim, config_sonja]
```

### Changing schedule
In `main.py`:
```python
# Update every 30 minutes
scheduler.add_job(
    update_render_data,
    trigger=IntervalTrigger(minutes=30),
    ...
)

# Send email at 08:00 (update CRONTRIGGER in config.py)
CRONTRIGGER = {"hour": "08", "minute": "00"}

# In main.py, this uses:
scheduler.add_job(
    send_app_via_email,
    trigger=CronTrigger(
        hour=config.CRONTRIGGER["hour"],
        minute=config.CRONTRIGGER["minute"],
        timezone="Europe/Berlin"
    ),
    ...
)
```

## Security Checklist

- [ ] `secrets.json` not in version control
- [ ] File permissions set correctly (600 for secrets.json)
- [ ] Using HTTPS in production
- [ ] Firewall configured (only necessary ports open)
- [ ] Regular updates of base images
- [ ] Rate limiting configured in nginx
- [ ] Security headers enabled

## Performance Optimization

### Nginx Caching
Static files cached for 1 year. To change:
```nginx
location /static/ {
    expires 30d;  # Change from 1y to 30d
}
```

### Rate Limiting
Default: 10 requests/second. To adjust:
```nginx
limit_req_zone $binary_remote_addr zone=api_limit:10m rate=20r/s;
```

### Memory Allocation
- Minimum: 4GB RAM
- Recommended: 8GB RAM
- Embedding model: ~500MB

## Backup Strategy

### Critical Files
```cmd
# Backup configuration and data
xcopy /E /I /Y "app\conf" "backup\app\conf"
xcopy /E /I /Y "nginx\conf" "backup\nginx\conf"
xcopy /E /I /Y "secrets" "backup\secrets"
xcopy /E /I /Y "clicktrack" "backup\clicktrack"
xcopy /E /I /Y "aux_data" "backup\aux_data"
```

### Automated Backup (Future)
Create a scheduled task to run daily backups.

## Docker Hub

- **Repository**: https://hub.docker.com/r/apollon67/newsreader
- **Tags**: `latest`, `amd64`
- **Pull**: `docker pull apollon67/newsreader:latest`

## Support

For detailed documentation, see: `doc/DOCKER_DEPLOYMENT.md`
