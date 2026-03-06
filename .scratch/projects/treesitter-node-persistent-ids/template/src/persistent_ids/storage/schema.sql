PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS file (
  file_id BLOB PRIMARY KEY,
  rel_path TEXT NOT NULL UNIQUE,
  language TEXT NOT NULL,
  content_hash BLOB NOT NULL,
  size_bytes INTEGER NOT NULL,
  mtime_ns INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS entity (
  entity_id BLOB PRIMARY KEY,
  kind TEXT NOT NULL,
  language TEXT NOT NULL,
  name TEXT NOT NULL,
  semantic_key TEXT NOT NULL,
  flags INTEGER NOT NULL DEFAULT 0,
  last_seen_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS entity_anchor (
  entity_id BLOB NOT NULL REFERENCES entity(entity_id),
  file_id BLOB NOT NULL REFERENCES file(file_id),
  content_hash BLOB NOT NULL,
  start_byte INTEGER NOT NULL,
  end_byte INTEGER NOT NULL,
  start_row INTEGER NOT NULL,
  start_col INTEGER NOT NULL,
  header_row INTEGER NOT NULL,
  PRIMARY KEY (entity_id, content_hash)
);

CREATE TABLE IF NOT EXISTS edge (
  src_entity_id BLOB NOT NULL REFERENCES entity(entity_id),
  edge_type TEXT NOT NULL,
  dst_entity_id BLOB NOT NULL REFERENCES entity(entity_id),
  file_id BLOB NULL REFERENCES file(file_id),
  PRIMARY KEY (src_entity_id, edge_type, dst_entity_id)
);

CREATE INDEX IF NOT EXISTS idx_entity_kind_lang ON entity(kind, language);
CREATE INDEX IF NOT EXISTS idx_anchor_file_version ON entity_anchor(file_id, content_hash, start_byte);
CREATE INDEX IF NOT EXISTS idx_edge_src_type ON edge(src_entity_id, edge_type);
