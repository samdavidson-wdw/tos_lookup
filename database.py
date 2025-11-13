# database.py
import sqlite3
from typing import List, Dict, Any
from pathlib import Path
from dotenv import load_dotenv
import os

load_dotenv()

DB_PATH = os.getenv("DB_PATH")

def get_connection():
    return sqlite3.connect(DB_PATH)

def build_where(search: str, status: str):
    where = []
    params = []
    if search := search.strip():
        like = f"%{search}%"
        where.append("(ShortDescription LIKE ? OR Number LIKE ?)")
        params.extend([like, like])
    if status and status != "All":
        where.append("State LIKE ?")
        params.append(f"%{status}%")
    clause = "WHERE " + " AND ".join(where) if where else ""
    return clause, params

def get_ticket_type(desc: str) -> str:
    desc = desc.lower()
    if "-ap" in desc or " ap down" in desc or "down ap" in desc:
        return "Access Point"
    if "sysmon" in desc:
        return "Sysmon"
    if "ont" in desc or "naba" in desc:
        return "ONT"
    return ""

def search_tickets(search: str, status: str, page: int, page_size: int = 50):
    page = max(1, page)
    offset = (page - 1) * page_size

    clause, params = build_where(search, status)

    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # Total
        total = cur.execute(f"SELECT COUNT(*) FROM tickets {clause}", params).fetchone()[0]

        # Page
        sql = f"""
            SELECT Number, Caller, ShortDescription, State, Created
            FROM tickets {clause}
            ORDER BY Created DESC
            LIMIT ? OFFSET ?
        """
        rows = cur.execute(sql, params + [page_size, offset]).fetchall()

        tickets = [
            {
                "id": r["Number"],
                "assignee": r["Caller"],
                "shortDescription": r["ShortDescription"],
                "status": r["State"],
                "createdAt": r["Created"],
                "type": get_ticket_type(r["ShortDescription"]),
            }
            for r in rows
        ]

        # Stats
        stats = {"total": total}

        # Helper: safely append condition
        def count_with_condition(condition):
            if clause:
                sql = f"SELECT COUNT(*) FROM tickets {clause} AND {condition}"
            else:
                sql = f"SELECT COUNT(*) FROM tickets WHERE {condition}"
            return cur.execute(sql, params).fetchone()[0]

        stats["resolved"] = count_with_condition("State IN ('Resolved','Closed','Cancelled')")
        stats["inProgress"] = count_with_condition("State IN ('Assigned','Work in Progress')")
        stats["pending"] = count_with_condition("State LIKE 'Pending%'")

    return {"tickets": tickets, "total": total, "stats": stats}

def export_tickets(search: str, status: str) -> List[Dict]:
    clause, params = build_where(search, status)
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        # Build base query safely
        base = "SELECT Number, Caller, ShortDescription, State, Created FROM tickets"
        if clause:
            sql = f"{base} {clause} ORDER BY Created DESC"
        else:
            sql = f"{base} ORDER BY Created DESC"
        rows = cur.execute(sql, params).fetchall()
        return [
            {
                "id": r["Number"],
                "assignee": r["Caller"],
                "shortDescription": r["ShortDescription"],
                "status": r["State"],
                "createdAt": r["Created"],
                "type": get_ticket_type(r["ShortDescription"]),
            }
            for r in rows
        ]