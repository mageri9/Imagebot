-- Users & whitelist
CREATE TABLE IF NOT EXISTS users (
    user_id     INTEGER PRIMARY KEY,
    username    TEXT,
    full_name   TEXT,
    daily_limit INTEGER  NOT NULL DEFAULT 10,
    balance     REAL     NOT NULL DEFAULT 0.0,  -- reserved for payments
    is_active   BOOLEAN  NOT NULL DEFAULT 1,
    added_by    INTEGER,                         -- admin user_id who added
    added_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Daily generation counter (resets automatically by date check in quota service)
CREATE TABLE IF NOT EXISTS daily_usage (
    user_id     INTEGER  NOT NULL,
    date        TEXT     NOT NULL,               -- ISO date: 2025-01-15
    count       INTEGER  NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, date),
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

-- Generation history
CREATE TABLE IF NOT EXISTS generations (
    id          INTEGER  PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER  NOT NULL,
    mode        TEXT     NOT NULL,               -- text | image | multi
    model       TEXT     NOT NULL,
    prompt      TEXT,
    created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    success     BOOLEAN  NOT NULL DEFAULT 1,
    error_msg   TEXT,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

-- Transactions (reserved for payments)
CREATE TABLE IF NOT EXISTS transactions (
    id          INTEGER  PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER  NOT NULL,
    amount      REAL     NOT NULL,
    type        TEXT     NOT NULL,               -- topup | spend
    comment     TEXT,
    created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

-- Bot settings (key-value: model, provider, etc.)
CREATE TABLE IF NOT EXISTS settings (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Seed default settings (INSERT OR IGNORE = не перезапишет если уже есть)
INSERT OR IGNORE INTO settings (key, value) VALUES ('image_model', 'gpt-image-1');
INSERT OR IGNORE INTO settings (key, value) VALUES ('image_size', '1024x1024');
INSERT OR IGNORE INTO settings (key, value) VALUES ('image_quality', 'medium');
INSERT OR IGNORE INTO settings (key, value) VALUES ('provider_base_url', '');
