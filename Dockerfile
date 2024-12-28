FROM python:3.12-slim

RUN python -m pip install --upgrade pip

WORKDIR /app

COPY requirements.txt .

RUN python -m pip install -r requirements.txt --upgrade

COPY . .

# Create required directories
RUN mkdir -p data downloads/temp

# Add a healthcheck to verify bot token exists
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD test -n "$BOT_TOKEN" && test -n "$SUDO_USERS" || exit 1

# Verify required environment variables
CMD if [ -z "$BOT_TOKEN" ]; then \
        echo "Error: BOT_TOKEN environment variable is required"; \
        exit 1; \
    elif [ -z "$SUDO_USERS" ]; then \
        echo "Error: SUDO_USERS environment variable is required"; \
        exit 1; \
    else \
        python bot.py; \
    fi