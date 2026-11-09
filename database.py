"""PostgreSQL compatibility layer for Mirage Leads Hunter.

The app keeps its small sqlite-style execute API so existing routes and local
Windows development continue to work. PostgreSQL is selected whenever
DATABASE_URL (or POSTGRES_URL) is configured.
"""
import re
import psycopg
from psycopg.rows import tuple_row


class HybridRow(dict):
    """Mapping row that also supports SQLite-style numeric indexing."""
    def __init__(self, names, values):
        super().__init__(zip(names, values))
        self._values = tuple(values)

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return super().__getitem__(key)


class Cursor:
    def __init__(self, cursor):
        self._cursor = cursor
        self.lastrowid = None
        self._names = []

    def execute(self, sql, params=()):
        statement = sql.strip()
        # SQLite schema introspection used by the original app.
        if statement.upper().startswith("PRAGMA TABLE_INFO("):
            table = re.search(r"PRAGMA\s+table_info\(([^)]+)\)", statement, re.I).group(1).strip('"')
            statement = (
                "SELECT ordinal_position, column_name FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = %s ORDER BY ordinal_position"
            )
            params = (table,)
        else:
            statement = re.sub(r"\bdatetime\('now'\s*,\s*'localtime'\)", "CURRENT_TIMESTAMP", statement, flags=re.I)
            statement = re.sub(r"date\(created\)\s*=\s*date\('now'\s*,\s*'localtime'\)", "created::date = CURRENT_DATE", statement, flags=re.I)
            statement = statement.replace("?", "%s")
            statement = re.sub(r"\bINTEGER\s+PRIMARY\s+KEY\b", "BIGSERIAL PRIMARY KEY", statement, flags=re.I)
            ignored = bool(re.match(r"INSERT\s+OR\s+IGNORE\s+INTO\b", statement, re.I))
            if ignored:
                statement = re.sub(r"INSERT\s+OR\s+IGNORE\s+INTO", "INSERT INTO", statement, count=1, flags=re.I)
            is_insert = bool(re.match(r"INSERT\s+INTO\b", statement, re.I))
            if is_insert:
                statement = statement.rstrip().rstrip(";")
                statement += " ON CONFLICT DO NOTHING" if ignored else ""
                statement += " RETURNING id"
        self._cursor.execute(statement, params or ())
        self._names = [d.name for d in self._cursor.description] if self._cursor.description else []
        if re.match(r"INSERT\s+INTO\b", statement, re.I) and self._names:
            row = self._cursor.fetchone()
            if row:
                self.lastrowid = row[0]
            self._names = []
        return self

    def _row(self, values):
        return HybridRow(self._names, values) if values is not None else None

    def fetchone(self):
        row = self._cursor.fetchone()
        return self._row(row) if row is not None else None

    def fetchall(self):
        return [self._row(row) for row in self._cursor.fetchall()]

    @property
    def rowcount(self):
        return self._cursor.rowcount


class Connection:
    def __init__(self, dsn):
        self._conn = psycopg.connect(dsn, row_factory=tuple_row, connect_timeout=12)
    def execute(self, sql, params=()):
        return Cursor(self._conn.cursor()).execute(sql, params)
    def commit(self):
        self._conn.commit()
    def rollback(self):
        self._conn.rollback()
    def close(self):
        self._conn.close()


def connect(dsn):
    return Connection(dsn)


def initialize(conn):
    statements = [
        """CREATE TABLE IF NOT EXISTS leads (
            id BIGSERIAL PRIMARY KEY, company TEXT, phone TEXT, email TEXT, website TEXT,
            country TEXT, keyword TEXT, score INTEGER DEFAULT 0, status TEXT DEFAULT 'new',
            owner TEXT DEFAULT '', source TEXT DEFAULT 'website', campaign TEXT DEFAULT '',
            external_id TEXT DEFAULT '', consent TEXT DEFAULT '', notes TEXT DEFAULT '',
            city TEXT DEFAULT '', created TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(phone, website))""",
        "ALTER TABLE leads ADD COLUMN IF NOT EXISTS notes TEXT DEFAULT ''",
        "ALTER TABLE leads ADD COLUMN IF NOT EXISTS city TEXT DEFAULT ''",
        "CREATE INDEX IF NOT EXISTS ix_leads_phone ON leads(phone)",
        """CREATE TABLE IF NOT EXISTS users (
            id BIGSERIAL PRIMARY KEY, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'sales', active INTEGER DEFAULT 1,
            created TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS audit_logs (
            id BIGSERIAL PRIMARY KEY, actor TEXT, action TEXT, entity TEXT, entity_id BIGINT,
            details TEXT DEFAULT '', created TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS batches (
            id BIGSERIAL PRIMARY KEY, name TEXT, keyword TEXT, country TEXT,
            created TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP, scanned INTEGER DEFAULT 0, added INTEGER DEFAULT 0)""",
        """CREATE TABLE IF NOT EXISTS activities (
            id BIGSERIAL PRIMARY KEY, lead_id BIGINT NOT NULL, actor TEXT NOT NULL,
            activity_type TEXT NOT NULL, note TEXT NOT NULL DEFAULT '',
            created TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS tasks (
            id BIGSERIAL PRIMARY KEY, lead_id BIGINT NOT NULL, assigned_to TEXT NOT NULL,
            title TEXT NOT NULL, due_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open',
            created_by TEXT NOT NULL, created TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS wa_log (
            id BIGSERIAL PRIMARY KEY, lead_id BIGINT, phone TEXT, ok INTEGER,
            note TEXT, created TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP)""",
    ]
    for statement in statements:
        conn.execute(statement)
    conn.commit()
