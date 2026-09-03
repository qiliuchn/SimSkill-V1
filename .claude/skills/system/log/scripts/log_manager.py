#!/usr/bin/env python3
"""
log_manager.py — CLI for updating log.md without loading it into LLM context.

All table operations use HTML-comment markers in log.md as anchors:
  <!--LOG_TABLE:PROCEDURAL--> ... <!--END_LOG_TABLE:PROCEDURAL-->
  <!--LOG_TABLE:SEMANTIC-->    ... <!--END_LOG_TABLE:SEMANTIC-->
  <!--LOG_TABLE:LINT_RECORDS--> ... <!--END_LOG_TABLE:LINT_RECORDS-->

The "open row" in the LINT_RECORDS table is identified by the sentinel
`_(open)_` in its first (Lint Run Timestamp) cell.  There must be exactly
one open row at the bottom of that table at all times.

Usage:
  log_manager.py get-open-count         [--log-path <path>]
  log_manager.py get-open-items          [--log-path <path>]
  log_manager.py get-open-row-info       [--log-path <path>]
  log_manager.py append-items <name>...  [--log-path <path>]
  log_manager.py close-open --timestamp <ts> [--findings <f>] [--actions <a>] [--log-path <path>]
  log_manager.py add-procedural-row --timestamp <ts> --item <n> --operation <op> --change <c> [--log-path <path>]
  log_manager.py add-semantic-row  --timestamp <ts> --item <n> --operation <op> --change <c> [--log-path <path>]
  log_manager.py count-rows              [--log-path <path>]
"""

import argparse
import json
import os
import sys

def _find_project_root(start_dir):
    """Walk upward from start_dir looking for CLAUDE.md, which marks the project root.

    Searching for a sentinel file instead of hardcoding a fixed number of parent
    directories keeps this correct even if this skill's own nesting depth under
    .claude/skills/ ever changes.
    """
    current = os.path.abspath(start_dir)
    while True:
        if os.path.isfile(os.path.join(current, "CLAUDE.md")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            raise RuntimeError(
                "could not locate project root: no CLAUDE.md found in any parent "
                f"directory of {start_dir}"
            )
        current = parent


# Resolving from __file__ rather than os.getcwd() keeps this correct regardless of the
# caller's working directory (subagents, worktrees, etc.).
PROJECT_ROOT = _find_project_root(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_LOG_PATH = os.path.join(PROJECT_ROOT, "log.md")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def read_log(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def write_log(path, content):
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def _markers(marker_id):
    return f"<!--LOG_TABLE:{marker_id}-->", f"<!--END_LOG_TABLE:{marker_id}-->"


def find_table(content, marker_id):
    """Return (table_start, table_end, table_text) or (None, None, None)."""
    start_tag, end_tag = _markers(marker_id)
    start = content.find(start_tag)
    if start == -1:
        return None, None, None
    end = content.find(end_tag, start)
    if end == -1:
        return None, None, None

    # table text begins after the first \n after the start tag
    table_start = content.index("\n", start) + 1
    # table text ends at the last \n before the end tag
    table_end = content.rfind("\n", 0, end)
    if table_end < table_start:
        table_end = end
    return table_start, table_end, content[table_start:table_end]


def parse_rows(table_text):
    """Parse a markdown table into a list of data rows (skipping header/sep)."""
    lines = table_text.strip().split("\n")
    rows = []
    in_header = True
    for line in lines:
        line = line.strip()
        if not line or line == "|---" or line.startswith("| ---") or not line.startswith("|"):
            continue
        # The first non-separator | line is the header — skip it
        if in_header:
            in_header = False
            continue
        cells = [c.strip() for c in line.split("|")]
        # remove leading/trailing empty cell from outer pipes
        if cells and cells[0] == "":
            cells = cells[1:]
        if cells and cells[-1] == "":
            cells = cells[:-1]
        rows.append(cells)
    return rows


def format_row(cells):
    """Render one markdown table row from a list of cell values."""
    # escape pipe characters inside cell content
    escaped = [c.replace("|", "\\|") for c in cells]
    return "| " + " | ".join(escaped) + " |"


def _locate_separator(lines):
    """Return index of the |--- separator line."""
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith("| ---") or s == "|---":
            return i
    return None


def rebuild_table(table_text, rows):
    """
    Given the original table text and updated row list, rebuild the full
    table including the original header & separator.
    """
    lines = table_text.strip().split("\n")
    sep = _locate_separator(lines)
    if sep is None:
        raise ValueError("cannot find table separator in existing table")
    header = "\n".join(lines[: sep + 1])
    body = "\n".join(format_row(r) for r in rows)
    return header + "\n" + body + "\n"


def _open_row(rows):
    """Return (index, row) of the open row (first cell == _(open)_), or None."""
    for i, row in enumerate(rows):
        if row and row[0].strip() == "_(open)_":
            return i, row
    return None, None


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------

def cmd_get_open_count(args):
    content = read_log(args.log_path)
    _, _, text = find_table(content, "LINT_RECORDS")
    if text is None:
        print("0")
        return
    rows = parse_rows(text)
    _, row = _open_row(rows)
    if row is None:
        print("0")
        return
    items = [i.strip() for i in row[1].split(",") if i.strip()] if len(row) >= 2 and row[1].strip() else []
    print(len(items))


def cmd_get_open_items(args):
    content = read_log(args.log_path)
    _, _, text = find_table(content, "LINT_RECORDS")
    if text is None:
        return
    rows = parse_rows(text)
    _, row = _open_row(rows)
    if row is None:
        return
    if len(row) >= 2 and row[1].strip():
        for item in row[1].split(","):
            item = item.strip()
            if item:
                print(item)


def cmd_get_open_row_info(args):
    content = read_log(args.log_path)
    _, _, text = find_table(content, "LINT_RECORDS")
    if text is None:
        print(json.dumps({"count": 0, "items": []}))
        return
    rows = parse_rows(text)
    _, row = _open_row(rows)
    if row is None:
        print(json.dumps({"count": 0, "items": []}))
        return
    items = [i.strip() for i in row[1].split(",") if i.strip()] if len(row) >= 2 and row[1].strip() else []
    print(json.dumps({"count": len(items), "items": items}))


def cmd_append_items(args):
    content = read_log(args.log_path)
    start, end, text = find_table(content, "LINT_RECORDS")
    if text is None:
        print("FATAL: LINT_RECORDS table not found (markers missing)", file=sys.stderr)
        sys.exit(1)

    rows = parse_rows(text)
    idx, row = _open_row(rows)
    if row is None:
        print("FATAL: no open row found (no _(open)_ sentinel)", file=sys.stderr)
        sys.exit(1)

    existing = row[1].strip() if len(row) >= 2 and row[1].strip() else ""
    addition = ", ".join(args.names)
    row[1] = (existing + ", " + addition) if existing else addition
    # Ensure 4 cells
    while len(row) < 4:
        row.append("")
    rows[idx] = row

    new_table = rebuild_table(text, rows)
    new_content = content[:start] + new_table + content[end:]
    write_log(args.log_path, new_content)
    print(f"appended {len(args.names)} item(s) to open row")


def cmd_close_open(args):
    content = read_log(args.log_path)
    start, end, text = find_table(content, "LINT_RECORDS")
    if text is None:
        print("FATAL: LINT_RECORDS table not found", file=sys.stderr)
        sys.exit(1)

    rows = parse_rows(text)
    idx, row = _open_row(rows)
    if row is None:
        print("FATAL: no open row found", file=sys.stderr)
        sys.exit(1)

    # Close the current open row
    items = row[1].strip() if len(row) >= 2 else ""
    closed = [args.timestamp, items, args.findings or "", args.actions or ""]
    rows[idx] = closed

    # Append a fresh open row
    rows.append(["_(open)_", "", "", ""])

    new_table = rebuild_table(text, rows)
    new_content = content[:start] + new_table + content[end:]
    write_log(args.log_path, new_content)
    print(f"closed open row at {args.timestamp} and created new open row")


def cmd_add_row(marker_id, args):
    content = read_log(args.log_path)
    start, end, text = find_table(content, marker_id)
    if text is None:
        print(f"FATAL: {marker_id} table not found", file=sys.stderr)
        sys.exit(1)

    rows = parse_rows(text)
    rows.append([args.timestamp, args.item, args.operation, args.change])

    new_table = rebuild_table(text, rows)
    new_content = content[:start] + new_table + content[end:]
    write_log(args.log_path, new_content)
    print(f"added row to {marker_id} table")


def cmd_count_rows(args):
    """Export row counts for all three tables as JSON (for reporting)."""
    content = read_log(args.log_path)
    result = {}
    for mid in ("PROCEDURAL", "SEMANTIC", "LINT_RECORDS"):
        _, _, text = find_table(content, mid)
        result[mid.lower()] = len(parse_rows(text)) if text else 0
    print(json.dumps(result))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Manage log.md (memory change log)")
    parser.add_argument(
        "--log-path",
        default=DEFAULT_LOG_PATH,
        help=f"path to log.md (default: {DEFAULT_LOG_PATH})",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # get-open-count
    sub.add_parser("get-open-count", help="print count of items in the open row")

    # get-open-items
    sub.add_parser("get-open-items", help="print item names in the open row, one per line")

    # get-open-row-info
    sub.add_parser("get-open-row-info", help="print open-row info as JSON")

    # append-items
    p = sub.add_parser("append-items", help="append item names to the open row")
    p.add_argument("names", nargs="+", help="item name(s) to append")

    # close-open
    p = sub.add_parser("close-open", help="close the open row and create a fresh one")
    p.add_argument("--timestamp", required=True, help="ISO-8601 timestamp")
    p.add_argument("--findings", default="", help="findings for the closed row")
    p.add_argument("--actions", default="", help="actions taken")

    # add-procedural-row
    p = sub.add_parser("add-procedural-row", help="add a row to the Procedural Memory table")
    for arg in ("timestamp", "item", "operation", "change"):
        p.add_argument(f"--{arg}", required=True)

    # add-semantic-row
    p = sub.add_parser("add-semantic-row", help="add a row to the Semantic Memory table")
    for arg in ("timestamp", "item", "operation", "change"):
        p.add_argument(f"--{arg}", required=True)

    # count-rows
    sub.add_parser("count-rows", help="export row counts as JSON")

    args = parser.parse_args()

    # route
    dispatch = {
        "get-open-count": cmd_get_open_count,
        "get-open-items": cmd_get_open_items,
        "get-open-row-info": cmd_get_open_row_info,
        "append-items": cmd_append_items,
        "close-open": cmd_close_open,
        "add-procedural-row": lambda a: cmd_add_row("PROCEDURAL", a),
        "add-semantic-row": lambda a: cmd_add_row("SEMANTIC", a),
        "count-rows": cmd_count_rows,
    }
    fn = dispatch.get(args.command)
    if fn:
        fn(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
