
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from mcp.server.fastmcp import FastMCP

# Store the database beside this Python file.
DB_PATH = Path(__file__).with_name("carenest.db")

mcp = FastMCP("CareNest", json_response=True)


def connect_db():
    """Open the local database and return a connection."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def initialize_db():
    """Create the tables the first time CareNest runs."""
    with connect_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS appointments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                date_time TEXT NOT NULL,
                notes TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'scheduled',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS care_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                note TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                due_at TEXT NOT NULL,
                completed INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS checklists (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS checklist_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                checklist_id INTEGER NOT NULL,
                item TEXT NOT NULL,
                completed INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (checklist_id)
                    REFERENCES checklists(id)
            );
        """)


def now_utc():
    return datetime.now(timezone.utc).isoformat()


def valid_text(value, field):
    """Reject empty or excessively long text."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must not be empty.")
    if len(value.strip()) > 500:
        raise ValueError(f"{field} must be 500 characters or fewer.")
    return value.strip()


@mcp.tool()
def get_welcome_message() -> str:
    """Introduce CareNest and explain what it can do."""
    return (
        "Welcome to CareNest! I can organize appointments, "
        "care notes, questions, reminders, and checklists."
    )


# APPOINTMENTS

@mcp.tool()
def create_appointment(
    title: str,
    date_time: str,
    notes: str = "",
) -> dict:
    """Save an appointment with its date, time, and optional notes.

    Use an ISO 8601 date/time, for example:
    2026-10-25T14:30:00+05:30
    """
    title = valid_text(title, "title")
    date_time = valid_text(date_time, "date_time")

    try:
        datetime.fromisoformat(date_time)
    except ValueError:
        return {"success": False, "error": "Use an ISO 8601 date/time."}

    notes = notes.strip()
    if len(notes) > 500:
        return {"success": False, "error": "Notes are too long."}

    with connect_db() as conn:
        cursor = conn.execute(
            """INSERT INTO appointments
               (title, date_time, notes, created_at)
               VALUES (?, ?, ?, ?)""",
            (title, date_time, notes, now_utc()),
        )
        appointment_id = cursor.lastrowid

    return {
        "success": True,
        "appointment_id": appointment_id,
        "message": f"Saved appointment: {title}",
    }


@mcp.tool()
def get_appointments(status: str = "scheduled") -> dict:
    """List appointments. Use scheduled, cancelled, or all."""
    if status not in ("scheduled", "cancelled", "all"):
        return {
            "success": False,
            "error": "Status must be scheduled, cancelled, or all.",
        }

    with connect_db() as conn:
        if status == "all":
            rows = conn.execute(
                "SELECT * FROM appointments ORDER BY date_time"
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT * FROM appointments
                   WHERE status = ? ORDER BY date_time""",
                (status,),
            ).fetchall()

    return {"success": True, "appointments": [dict(r) for r in rows]}


@mcp.tool()
def cancel_appointment(appointment_id: int) -> dict:
    """Cancel an existing appointment using its ID."""
    with connect_db() as conn:
        cursor = conn.execute(
            """UPDATE appointments SET status = 'cancelled'
               WHERE id = ? AND status = 'scheduled'""",
            (appointment_id,),
        )
        if cursor.rowcount == 0:
            return {
                "success": False,
                "error": "Appointment not found or already cancelled.",
            }

    return {"success": True, "message": "Appointment cancelled."}


# CARE NOTES AND QUESTIONS

@mcp.tool()
def save_care_note(note: str) -> dict:
    """Save a general care note for later reference."""
    note = valid_text(note, "note")

    with connect_db() as conn:
        cursor = conn.execute(
            "INSERT INTO care_notes (note, created_at) VALUES (?, ?)",
            (note, now_utc()),
        )

    return {"success": True, "note_id": cursor.lastrowid}


@mcp.tool()
def get_care_notes() -> dict:
    """Retrieve saved care notes in newest-first order."""
    with connect_db() as conn:
        rows = conn.execute(
            "SELECT * FROM care_notes ORDER BY id DESC"
        ).fetchall()

    return {"success": True, "notes": [dict(r) for r in rows]}


@mcp.tool()
def save_question(question: str) -> dict:
    """Save a question to ask a care professional later."""
    question = valid_text(question, "question")

    with connect_db() as conn:
        cursor = conn.execute(
            "INSERT INTO questions (question, created_at) VALUES (?, ?)",
            (question, now_utc()),
        )

    return {"success": True, "question_id": cursor.lastrowid}


@mcp.tool()
def get_questions() -> dict:
    """List questions saved for a future care appointment."""
    with connect_db() as conn:
        rows = conn.execute(
            "SELECT * FROM questions ORDER BY id DESC"
        ).fetchall()

    return {"success": True, "questions": [dict(r) for r in rows]}


# REMINDERS

@mcp.tool()
def create_reminder(title: str, due_at: str) -> dict:
    """Save a reminder with an ISO 8601 due date/time.

    This stores a reminder; it does not send a notification.
    """
    title = valid_text(title, "title")
    due_at = valid_text(due_at, "due_at")

    try:
        datetime.fromisoformat(due_at)
    except ValueError:
        return {"success": False, "error": "Use an ISO 8601 date/time."}

    with connect_db() as conn:
        cursor = conn.execute(
            """INSERT INTO reminders (title, due_at, created_at)
               VALUES (?, ?, ?)""",
            (title, due_at, now_utc()),
        )

    return {
        "success": True,
        "reminder_id": cursor.lastrowid,
        "message": f"Saved reminder: {title}",
    }


@mcp.tool()
def get_reminders(include_completed: bool = False) -> dict:
    """List reminders that still need attention, or include completed ones."""
    with connect_db() as conn:
        if include_completed:
            rows = conn.execute(
                "SELECT * FROM reminders ORDER BY due_at"
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT * FROM reminders
                   WHERE completed = 0 ORDER BY due_at"""
            ).fetchall()

    return {"success": True, "reminders": [dict(r) for r in rows]}


@mcp.tool()
def complete_reminder(reminder_id: int) -> dict:
    """Mark an existing reminder as completed."""
    with connect_db() as conn:
        cursor = conn.execute(
            "UPDATE reminders SET completed = 1 WHERE id = ?",
            (reminder_id,),
        )
        if cursor.rowcount == 0:
            return {"success": False, "error": "Reminder not found."}

    return {"success": True, "message": "Reminder completed."}


# CHECKLISTS

@mcp.tool()
def create_checklist(title: str, items: list[str]) -> dict:
    """Create a checklist with its initial items."""
    title = valid_text(title, "title")

    if not items or len(items) > 50:
        return {
            "success": False,
            "error": "Provide between 1 and 50 checklist items.",
        }

    try:
        items = [valid_text(item, "item") for item in items]
    except ValueError as exc:
        return {"success": False, "error": str(exc)}

    with connect_db() as conn:
        cursor = conn.execute(
            "INSERT INTO checklists (title, created_at) VALUES (?, ?)",
            (title, now_utc()),
        )
        checklist_id = cursor.lastrowid

        conn.executemany(
            """INSERT INTO checklist_items
               (checklist_id, item) VALUES (?, ?)""",
            [(checklist_id, item) for item in items],
        )

    return {
        "success": True,
        "checklist_id": checklist_id,
        "message": f"Created checklist: {title}",
    }


@mcp.tool()
def get_checklist(checklist_id: int) -> dict:
    """Retrieve a checklist and its items using the checklist ID."""
    with connect_db() as conn:
        checklist = conn.execute(
            "SELECT * FROM checklists WHERE id = ?",
            (checklist_id,),
        ).fetchone()

        if checklist is None:
            return {"success": False, "error": "Checklist not found."}

        items = conn.execute(
            """SELECT id, item, completed FROM checklist_items
               WHERE checklist_id = ? ORDER BY id""",
            (checklist_id,),
        ).fetchall()

    return {
        "success": True,
        "checklist": dict(checklist),
        "items": [dict(item) for item in items],
    }


@mcp.tool()
def update_checklist_item(item_id: int, completed: bool) -> dict:
    """Mark a checklist item complete or incomplete."""
    with connect_db() as conn:
        cursor = conn.execute(
            "UPDATE checklist_items SET completed = ? WHERE id = ?",
            (int(completed), item_id),
        )
        if cursor.rowcount == 0:
            return {"success": False, "error": "Checklist item not found."}

    return {"success": True, "message": "Checklist item updated."}


if __name__ == "__main__":
    initialize_db()
    mcp.run(transport="streamable-http")
