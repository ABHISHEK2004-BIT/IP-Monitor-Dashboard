PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS ips (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ip TEXT NOT NULL UNIQUE,
    name TEXT,
    device_type TEXT,
    importance TEXT,
    remark TEXT,
    last_status TEXT,
    last_ping_ms REAL,
    last_checked TEXT
);

CREATE TABLE IF NOT EXISTS ping_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ip_id INTEGER NOT NULL,
    ts TEXT NOT NULL,
    status TEXT NOT NULL,
    ping_ms REAL,
    FOREIGN KEY(ip_id) REFERENCES ips(id) ON DELETE CASCADE
);

-- Optional sample rows (won't duplicate)
INSERT OR IGNORE INTO ips (ip, name, device_type, importance, remark)
VALUES
  ('8.8.8.8','Google DNS','other','important','Public DNS'),
  ('1.1.1.1','Cloudflare DNS','other','important','Public DNS');
