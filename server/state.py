from __future__ import annotations

from pathlib import Path
import sqlite3


class LocalState:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self._init_schema()

    def _init_schema(self) -> None:
        cur = self.conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS account (
                username TEXT PRIMARY KEY,
                session_token TEXT NOT NULL,
                last_login_utc TEXT NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS character_state (
                username TEXT PRIMARY KEY,
                scene_id TEXT NOT NULL DEFAULT 'school_gate',
                x REAL NOT NULL DEFAULT 0,
                y REAL NOT NULL DEFAULT 0,
                z REAL NOT NULL DEFAULT 0,
                FOREIGN KEY(username) REFERENCES account(username)
            )
            """
        )
        self.conn.commit()

    def upsert_login(self, username: str, token: str, login_utc: str) -> None:
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO account(username, session_token, last_login_utc)
            VALUES(?, ?, ?)
            ON CONFLICT(username) DO UPDATE SET
                session_token=excluded.session_token,
                last_login_utc=excluded.last_login_utc
            """,
            (username, token, login_utc),
        )
        cur.execute(
            """
            INSERT INTO character_state(username)
            VALUES(?)
            ON CONFLICT(username) DO NOTHING
            """,
            (username,),
        )
        self.conn.commit()

    def get_character(self, username: str) -> dict[str, object]:
        cur = self.conn.cursor()
        row = cur.execute(
            "SELECT scene_id, x, y, z FROM character_state WHERE username=?",
            (username,),
        ).fetchone()
        if row is None:
            return {"scene_id": "school_gate", "x": 0.0, "y": 0.0, "z": 0.0}
        return {"scene_id": row[0], "x": row[1], "y": row[2], "z": row[3]}

    def update_position(self, username: str, x: float, y: float, z: float) -> None:
        cur = self.conn.cursor()
        cur.execute(
            """
            UPDATE character_state SET x=?, y=?, z=?
            WHERE username=?
            """,
            (x, y, z, username),
        )
        self.conn.commit()
