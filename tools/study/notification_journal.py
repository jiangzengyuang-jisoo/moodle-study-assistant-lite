"""Durable, append-only observations. Semantic review receipts live in state.json."""
import json
import hashlib
import sqlite3
import uuid
from datetime import datetime

class Journal:
    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=30)
        try:
            self.db.row_factory = sqlite3.Row
            self.db.executescript("""
              PRAGMA synchronous=FULL;
              CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
              CREATE TABLE IF NOT EXISTS events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT UNIQUE NOT NULL,
                source_id TEXT NOT NULL, hash TEXT NOT NULL, availability TEXT NOT NULL,
                record TEXT NOT NULL, checked_at TEXT, inherited_review INTEGER NOT NULL DEFAULT 0);
              CREATE TABLE IF NOT EXISTS current (
                source_id TEXT PRIMARY KEY, hash TEXT NOT NULL, availability TEXT NOT NULL,
                record TEXT NOT NULL, event_id TEXT NOT NULL);
              CREATE INDEX IF NOT EXISTS events_source ON events(source_id, seq);
              CREATE TABLE IF NOT EXISTS processed_snapshots (fingerprint TEXT PRIMARY KEY);
              CREATE TABLE IF NOT EXISTS last_observed (
                source_id TEXT PRIMARY KEY, hash TEXT NOT NULL, availability TEXT NOT NULL);
              INSERT OR IGNORE INTO last_observed(source_id,hash,availability)
                SELECT source_id,hash,availability FROM current;
            """)
            self.db.commit()
        except BaseException:
            self.db.close()
            raise

    def close(self):
        self.db.close()

    def empty(self):
        return self.db.execute("SELECT 1 FROM events LIMIT 1").fetchone() is None

    def ingest(self, records, snapshot, legacy=None):
        stamp = snapshot.get("finished_at")
        if not stamp:
            raise ValueError("采集快照缺少完成时间，不能推进通知记录")
        epoch = datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
        # Wall-clock order is not a delivery ID: clocks can move backwards and
        # spool files can arrive late. Deduplicate the exact durable observation.
        fingerprint = hashlib.sha256(json.dumps(
            {"snapshot": snapshot, "records": records}, sort_keys=True,
            ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        complete = snapshot.get("collection_complete") is True
        added = 0
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            if self.db.execute("SELECT 1 FROM processed_snapshots WHERE fingerprint=?", (fingerprint,)).fetchone():
                return 0
            old_stamp = self.db.execute("SELECT value FROM meta WHERE key='epoch'").fetchone()
            late = bool(old_stamp and epoch < float(old_stamp[0]))
            bootstrap = self.empty()
            old = {r["source_id"]: dict(r) for r in self.db.execute("SELECT * FROM current")}
            observed = {r["source_id"]: dict(r) for r in self.db.execute("SELECT * FROM last_observed")}

            def append(r, availability):
                nonlocal added
                identity = r["id"]
                previous = (observed if late else old).get(identity)
                unchanged = previous and previous["hash"] == r["hash"] and previous["availability"] == availability
                # Remember arrival order only for deduplicating repeated late
                # bodies. A late snapshot never replaces the chronological head.
                self.db.execute("INSERT OR REPLACE INTO last_observed VALUES(?,?,?)",
                                (identity, r["hash"], availability))
                if unchanged:
                    return
                eid = uuid.uuid4().hex
                body = json.dumps(r, ensure_ascii=False, separators=(",", ":"))
                inherited = int(bootstrap and availability == "visible" and
                                (legacy or {}).get(identity, {}).get("hash") == r["hash"])
                self.db.execute("INSERT INTO events(event_id,source_id,hash,availability,record,checked_at,inherited_review) VALUES(?,?,?,?,?,?,?)",
                                (eid, identity, r["hash"], "observed_late" if late else availability, body, stamp, inherited))
                if not late:
                    self.db.execute("INSERT OR REPLACE INTO current VALUES(?,?,?,?,?)",
                                    (identity, r["hash"], availability, body, eid))
                added += 1

            for r in records.values():
                append(r, "visible")
            if complete and not late:
                for identity, previous in old.items():
                    if identity not in records:
                        r = json.loads(previous["record"])
                        append(r, "resolved" if r["kind"] == "collection_issue" else "no_longer_visible")
            # Archive and fingerprint commit together; the spool can then be
            # removed safely even when this was an older complete snapshot.
            self.db.execute("INSERT INTO processed_snapshots VALUES(?)", (fingerprint,))
            if not late:
                self.db.execute("INSERT OR REPLACE INTO meta VALUES('epoch',?)", (str(epoch),))
        return added

    def events(self):
        result = []
        for row in self.db.execute("SELECT * FROM events ORDER BY seq"):
            item = dict(row)
            item["record"] = json.loads(item["record"])
            result.append(item)
        return result

    def event(self, event_id):
        row = self.db.execute("SELECT * FROM events WHERE event_id=?", (event_id,)).fetchone()
        if row is None:
            raise ValueError("通知版本不存在")
        item = dict(row)
        item["record"] = json.loads(item["record"])
        return item

    def latest(self, source_id):
        row = self.db.execute("SELECT event_id FROM current WHERE source_id=?", (source_id,)).fetchone()
        if row is None:
            # An older spool may contain a source absent from every newer head.
            # It is still readable/reviewable, explicitly labelled observed_late.
            row = self.db.execute("SELECT event_id FROM events WHERE source_id=? ORDER BY seq DESC LIMIT 1", (source_id,)).fetchone()
        if row is None:
            raise ValueError("未找到来源；当前不可见不代表学校已删除")
        return self.event(row[0])

    def pending(self, receipts):
        return [e for e in self.events() if not e["inherited_review"] and
                receipts.get(e["event_id"], {}).get("hash") != e["hash"]]
