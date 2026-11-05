-- Included by seed/check scripts with:  \ir ref_include.inc
-- Pins "now" so every date in the dataset is reproducible. The loader passes
--   psql -v ref_now="'2026-11-05 12:00:00+00'"
-- Use pg_temp.ref() instead of NOW() everywhere in seed and check scripts.
SELECT set_config('app.ref_now', :ref_now, false);
CREATE FUNCTION pg_temp.ref() RETURNS timestamptz LANGUAGE sql STABLE
AS $$ SELECT current_setting('app.ref_now')::timestamptz $$;
