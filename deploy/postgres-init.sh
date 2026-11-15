#!/bin/sh
set -eu
# psql variables quote the random password as data, never SQL source.
app_password=$(cat /run/secrets/postgres_app_password)
psql --set=ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
    --set=app_password="$app_password" <<'SQL'
CREATE ROLE p06_app LOGIN PASSWORD :'app_password';
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT CONNECT ON DATABASE p06 TO p06_app;
GRANT USAGE ON SCHEMA public TO p06_app;
ALTER DEFAULT PRIVILEGES FOR ROLE p06_owner IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO p06_app;
ALTER DEFAULT PRIVILEGES FOR ROLE p06_owner IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO p06_app;
SQL
unset app_password
