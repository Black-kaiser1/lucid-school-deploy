"""
db_adapter.py — Smart dual-mode database adapter.

Detects DATABASE_URL env var:
  - If set    → uses PostgreSQL (psycopg2) for production (Render, Railway, etc.)
  - If not set → uses SQLite for local development

Key features:
  • Auto-translates  ?  →  %s  so ALL existing app.py queries work unchanged
  • Auto-rewrites  INSERT OR IGNORE  →  INSERT ... ON CONFLICT DO NOTHING
  • Returns SmartRow objects that support BOTH row[0] AND row['col'] access
  • executescript() polyfill for PostgreSQL (splits on ; and runs each statement)
"""
import os, re, sqlite3

DATABASE_URL = os.environ.get('DATABASE_URL', '')

# ── Row wrapper ──────────────────────────────────────────────────────────────
class SmartRow(dict):
    """Dict that also supports integer index access.
    Works exactly like sqlite3.Row so existing code needs zero changes.
    """
    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)

    def get(self, key, default=None):
        return super().get(key, default)

    def keys(self):
        return super().keys()


# ── Cursor wrapper ───────────────────────────────────────────────────────────
_INSERT_OR_IGNORE = re.compile(r'INSERT\s+OR\s+IGNORE\s+INTO', re.IGNORECASE)
_REPLACE_INTO     = re.compile(r'REPLACE\s+INTO', re.IGNORECASE)

def _pg_sql(sql):
    """Translate SQLite-dialect SQL to PostgreSQL-dialect."""
    sql = sql.replace('?', '%s')
    if _INSERT_OR_IGNORE.search(sql):
        sql = _INSERT_OR_IGNORE.sub('INSERT INTO', sql)
        sql = sql.rstrip().rstrip(';') + ' ON CONFLICT DO NOTHING'
    if _REPLACE_INTO.search(sql):
        sql = _REPLACE_INTO.sub('INSERT INTO', sql)
        sql = sql.rstrip().rstrip(';') + ' ON CONFLICT DO NOTHING'
    return sql

def _sqlite_sql(sql):
    """Translate PostgreSQL-dialect SQL back to SQLite for local dev."""
    import re
    # STRING_AGG(expr, sep) → GROUP_CONCAT(expr, sep)
    # Handle: STRING_AGG(CAST(subject_id AS TEXT)||..., ',')
    sql = re.sub(
        r'STRING_AGG\s*\((.+?),\s*(\'.+?\')\)',
        lambda m: f"GROUP_CONCAT({_simplify_string_agg_expr(m.group(1))}, {m.group(2)})",
        sql, flags=re.DOTALL | re.IGNORECASE
    )
    # CAST(x AS NUMERIC) → x  (SQLite is loosely typed)
    sql = re.sub(r'CAST\s*\((.+?)\s+AS\s+(?:TEXT|NUMERIC|INTEGER)\)', r'\1', sql, flags=re.IGNORECASE)
    return sql

def _simplify_string_agg_expr(expr):
    """Remove CAST wrappers from STRING_AGG inner expression for SQLite."""
    import re
    expr = re.sub(r'CAST\s*\((.+?)\s+AS\s+(?:TEXT|NUMERIC|INTEGER)\)', r'\1', expr, flags=re.IGNORECASE)
    return expr


class SmartCursor:
    def __init__(self, raw_cursor, is_pg):
        self._c   = raw_cursor
        self._pg  = is_pg

    def execute(self, sql, params=None):
        if self._pg:
            sql = _pg_sql(sql)
        else:
            sql = _sqlite_sql(sql)
        self._c.execute(sql, params or ())
        return self

    def executemany(self, sql, seq):
        if self._pg:
            sql = _pg_sql(sql)
        self._c.executemany(sql, seq)
        return self

    def fetchone(self):
        row = self._c.fetchone()
        if row is None:
            return None
        if self._pg:
            return SmartRow(row)          # psycopg2 RealDictRow → SmartRow
        # sqlite3.Row → SmartRow
        return SmartRow({k: row[k] for k in row.keys()})

    def fetchall(self):
        rows = self._c.fetchall()
        if self._pg:
            return [SmartRow(r) for r in rows]
        return [SmartRow({k: r[k] for k in r.keys()}) for r in rows]

    @property
    def lastrowid(self):
        if self._pg:
            # PostgreSQL: use RETURNING id or currval
            try:
                row = self._c.fetchone()
                if row:
                    vals = list(row.values())
                    return vals[0] if vals else None
            except Exception:
                return None
        return self._c.lastrowid

    @property
    def rowcount(self):
        return self._c.rowcount

    def close(self):
        self._c.close()

    def __iter__(self):
        for row in self._c:
            if self._pg:
                yield SmartRow(row)
            else:
                yield SmartRow({k: row[k] for k in row.keys()})


# ── Connection wrapper ───────────────────────────────────────────────────────
class SmartConnection:
    def __init__(self, raw_conn, is_pg):
        self._conn = raw_conn
        self._pg   = is_pg

    def cursor(self):
        if self._pg:
            import psycopg2.extras
            return SmartCursor(
                self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor),
                is_pg=True
            )
        cur = self._conn.cursor()
        return SmartCursor(cur, is_pg=False)

    def execute(self, sql, params=None):
        """Convenience: connection-level execute (like sqlite3 allows)."""
        cur = self.cursor()
        cur.execute(sql, params)
        return cur

    def executemany(self, sql, seq):
        cur = self.cursor()
        cur.executemany(sql, seq)
        return cur

    def executescript(self, script):
        """PostgreSQL polyfill: split on ; and run each statement."""
        if self._pg:
            cur = self.cursor()
            for stmt in script.split(';'):
                stmt = stmt.strip()
                if stmt:
                    try:
                        cur._c.execute(stmt)
                    except Exception as e:
                        # Log but don't crash on IF NOT EXISTS duplicates
                        if 'already exists' not in str(e).lower():
                            raise
        else:
            self._conn.executescript(script)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.rollback()
        else:
            self.commit()
        self.close()


# ── Public get_db() ──────────────────────────────────────────────────────────
def get_db():
    """
    Returns a SmartConnection.
    Use DATABASE_URL env var for PostgreSQL (production).
    Falls back to SQLite for local development.
    """
    if DATABASE_URL:
        import psycopg2
        url = DATABASE_URL
        # Render gives postgres:// — psycopg2 needs postgresql://
        if url.startswith('postgres://'):
            url = 'postgresql://' + url[len('postgres://'):]
        raw = psycopg2.connect(url)
        raw.autocommit = False
        return SmartConnection(raw, is_pg=True)
    else:
        db_path = os.path.join(os.path.dirname(__file__), 'instance', 'saas_school.db')
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        raw = sqlite3.connect(db_path)
        raw.row_factory = sqlite3.Row
        raw.execute("PRAGMA foreign_keys = ON")
        return SmartConnection(raw, is_pg=False)


def is_postgres():
    return bool(DATABASE_URL)
