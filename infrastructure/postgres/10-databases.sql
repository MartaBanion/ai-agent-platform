\getenv platform_password PLATFORM_DB_PASSWORD
\getenv langflow_password LANGFLOW_DB_PASSWORD

BEGIN;
CREATE ROLE platform_app LOGIN PASSWORD :'platform_password';
CREATE ROLE langflow_app LOGIN PASSWORD :'langflow_password';
COMMIT;

CREATE DATABASE platform OWNER platform_app;
CREATE DATABASE langflow OWNER langflow_app;

REVOKE ALL ON DATABASE platform, langflow, postgres, template1 FROM PUBLIC;
