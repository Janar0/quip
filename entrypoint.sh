#!/bin/sh
# Persist JWT_SECRET across Docker restarts using the data volume.
# If JWT_SECRET is not explicitly set (or is the default placeholder),
# generate one on first run and reuse it on subsequent runs.
SECRET_FILE="/app/data/.jwt_secret"
DEFAULT="dev-secret-change-in-production"

if [ -z "$JWT_SECRET" ] || [ "$JWT_SECRET" = "$DEFAULT" ]; then
  if [ -f "$SECRET_FILE" ]; then
    JWT_SECRET=$(cat "$SECRET_FILE")
  else
    JWT_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    echo "$JWT_SECRET" > "$SECRET_FILE"
    chmod 600 "$SECRET_FILE"
  fi
  export JWT_SECRET
fi

exec supervisord -n
