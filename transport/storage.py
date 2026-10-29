"""CSV / JSON / SQL export and typed CSV loading (schema-driven)."""
import contextlib
import csv
import gzip
import hashlib
import io
import json
import os

from .schema import TABLE_BY_NAME, TABLES, ddl


@contextlib.contextmanager
def open_text(path):
    """Text writer; '.gz' paths are gzip-compressed with a fixed mtime so output is
    byte-for-byte reproducible."""
    if path.endswith(".gz"):
        with open(path, "wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz, \
                io.TextIOWrapper(gz, encoding="utf-8", newline="") as fh:
            yield fh
    else:
        with open(path, "w", encoding="utf-8", newline="") as fh:
            yield fh


def _cell(v):
    if v is None:
        return ""
    if v is True:
        return "true"
    if v is False:
        return "false"
    return str(v)


def _row_values(table, row):
    if isinstance(row, dict):
        return [row.get(c) for c in table.columns]
    return list(row)


def write_csv(path, table, rows):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(table.columns)
        for r in rows:
            w.writerow([_cell(v) for v in _row_values(table, r)])


def write_json(path, table, rows):
    cols = table.columns
    with open_text(path) as fh:
        fh.write("[\n")
        first = True
        for r in rows:
            obj = dict(zip(cols, _row_values(table, r)))
            fh.write(("" if first else ",\n") + json.dumps(obj, ensure_ascii=False, separators=(",", ":")))
            first = False
        fh.write("\n]\n")


def _sql(v):
    if v is None:
        return "NULL"
    if v is True:
        return "1"
    if v is False:
        return "0"
    if isinstance(v, (int, float)):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


def write_sql(schema_path, seed_path, tables_rows, batch=500):
    with open(schema_path, "w", encoding="utf-8") as fh:
        fh.write(ddl())
    with open_text(seed_path) as fh:
        fh.write("-- Seed data. Load after schema.sql (e.g. sqlite3 db < schema.sql; sqlite3 db < seed.sql)\n")
        fh.write("PRAGMA foreign_keys = ON;\nBEGIN TRANSACTION;\n")
        for t in TABLES:
            rows = tables_rows[t.name]
            cols = ", ".join(t.columns)
            buf = []
            for r in rows:
                buf.append("(" + ", ".join(_sql(v) for v in _row_values(t, r)) + ")")
                if len(buf) == batch:
                    fh.write(f"INSERT INTO {t.name} ({cols}) VALUES\n" + ",\n".join(buf) + ";\n")
                    buf = []
            if buf:
                fh.write(f"INSERT INTO {t.name} ({cols}) VALUES\n" + ",\n".join(buf) + ";\n")
        fh.write("COMMIT;\n")


def write_plain_csv(path, rows, columns):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(columns)
        for r in rows:
            w.writerow([_cell(r.get(c)) for c in columns])


def write_json_obj(path, obj):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2, ensure_ascii=False, sort_keys=False)
        fh.write("\n")


# ------------------------------------------------------------------ loading
def _parser(ftype):
    if ftype == "int":
        return int
    if ftype == "float":
        return float
    if ftype == "bool":
        def b(v):
            if v == "true":
                return True
            if v == "false":
                return False
            raise ValueError(f"bad bool {v!r}")
        return b
    return str


def iter_rows(csv_dir, name, errors=None):
    """Yield typed dicts. Unparseable cells are kept as raw strings and reported."""
    t = TABLE_BY_NAME[name]
    parsers = {f.name: _parser(f.type) for f in t.fields}
    cache = {}
    with open(os.path.join(csv_dir, f"{name}.csv"), newline="", encoding="utf-8") as fh:
        r = csv.reader(fh)
        header = next(r)
        if errors is not None and header != t.columns:
            errors.append(f"{name}: header mismatch {header}")
        for line in r:
            row = {}
            for col, raw in zip(header, line):
                if raw == "":
                    row[col] = None
                    continue
                try:
                    v = parsers[col](raw)
                except (ValueError, KeyError):
                    if errors is not None:
                        errors.append(f"{name}.{col}: cannot parse {raw!r}")
                    v = raw
                if isinstance(v, str) and len(v) <= 24:
                    v = cache.setdefault(v, v)
                row[col] = v
            yield row


def load_table(csv_dir, name, errors=None):
    return list(iter_rows(csv_dir, name, errors))


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def count_lines(path):
    with open(path, "rb") as fh:
        return sum(1 for _ in fh)
