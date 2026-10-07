#!/bin/sh
# Use the same persistent signing-key resolver as local uvicorn startup.
# Its default is /app/data/.jwt_secret in this image; JWT_SECRET_FILE overrides it.
python -m quip.core.security || exit 1

python -m quip.migrations.runner || exit 1

exec supervisord -n
