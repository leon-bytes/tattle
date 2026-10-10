-- Tattle schema. The backend applies this file every time it connects; every statement is safe to repeat.
--
-- What is stored: history for our own lab phones only (devices marked persist: true), and
-- only for sessions that ran while the device was marked. Phones that are not marked never
-- reach this database.

-- The knowledge base, mirrored from data/kb.json and data/kb_overrides.json at startup.
CREATE TABLE IF NOT EXISTS kb_domains (
    domain    text PRIMARY KEY,
    company   text,
    category  text NOT NULL,
    source    text NOT NULL               -- 'list' or 'override'
);

-- Lab phones. device_id is the phone's address on the hotspot.
CREATE TABLE IF NOT EXISTS devices (
    device_id  text PRIMARY KEY,
    name       text,
    persist    boolean NOT NULL DEFAULT true,
    updated    timestamptz NOT NULL DEFAULT now()
);

-- One row per recorded session (one app, one lab phone).
CREATE TABLE IF NOT EXISTS sessions (
    id         uuid PRIMARY KEY,
    device_id  text NOT NULL REFERENCES devices (device_id),
    label      text,                      -- the app name typed in the UI
    started    timestamptz NOT NULL,
    stopped    timestamptz                -- NULL while running, or if the backend stopped first
);

-- Lookups seen during a recorded session. Deleting the session deletes its hits.
CREATE TABLE IF NOT EXISTS hits (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id    uuid NOT NULL REFERENCES sessions (id) ON DELETE CASCADE,
    ts            timestamptz NOT NULL,
    domain        text NOT NULL,
    company       text,
    category      text NOT NULL,
    source        text NOT NULL,          -- 'list', 'override', 'ai' or 'unknown'
    blocked       boolean NOT NULL DEFAULT false,
    block_reason  text                    -- 'user', 'guard' or NULL
);
CREATE INDEX IF NOT EXISTS hits_session_idx ON hits (session_id);

-- AI answers for names no list knows, kept so the model is not asked twice.
CREATE TABLE IF NOT EXISTS ai_cache (
    domain      text PRIMARY KEY,
    company     text,
    category    text NOT NULL,
    confidence  real NOT NULL,
    model       text,
    created     timestamptz NOT NULL DEFAULT now()
);
