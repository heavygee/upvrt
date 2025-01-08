# UpVRT - Discord Video Upload Tool

Docker image for UpVRT, a tool for automatically compressing and uploading videos to Discord while maintaining quality under Discord's file size limits.

## Quick Start

```bash
docker pull heavygee/upvrt:latest
docker run -d \
  -p 7001:7001 \
  --name upvrt \
  -v /path/to/your/videos:/app/uploads \
  --env-file .env \
  heavygee/upvrt:latest
```

## Docker Compose

```yaml
version: '3.8'
services:
  upvrt:
    image: heavygee/upvrt:latest
    container_name: upvrt
    ports:
      - "7001:7001"
    volumes:
      - /path/to/your/videos:/app/uploads
    env_file:
      - .env
    restart: unless-stopped
```

## Environment Variables

Copy `.env.example` to `.env` and configure the required environment variables. See our [GitHub repository](https://github.com/HeavyGee/upvrt) for full configuration details and Discord bot setup instructions.

## Documentation

For complete documentation, including:
- Discord bot setup
- Configuration options
- Manual installation
- Troubleshooting

Please visit our [GitHub repository](https://github.com/HeavyGee/upvrt). 