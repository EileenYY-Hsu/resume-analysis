import sqlite3
from datetime import datetime
import configparser
import os

# 讀取 config_run.ini 中的 SQLite 檔案路徑
config = configparser.ConfigParser()
config.read('config_run.ini', encoding='utf-8')

DB_FILE = config.get('DATABASE', 'db_file', fallback='resume.db').strip()
if not os.path.isabs(DB_FILE):
    DB_FILE = os.path.join(os.path.dirname(__file__), DB_FILE)


def get_connection():
    """建立並回傳 SQLite 連線"""
    conn = sqlite3.connect(DB_FILE, timeout=30.0, detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """初始化資料庫與資料表"""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS curriculum_vitae (
                interview_state TEXT,
                is_screened TEXT,
                name TEXT,
                code TEXT PRIMARY KEY,
                age TEXT,
                total_work_years TEXT,
                it_work_years TEXT,
                autobiography TEXT,
                work_experience TEXT,
                highest_edu_level TEXT,
                highest_edu_school TEXT,
                highest_edu_major TEXT,
                highest_edu_period TEXT,
                second_edu_school TEXT,
                second_edu_major TEXT,
                tech_skills TEXT,
                key_highlights TEXT,
                notes TEXT,
                score_data_eng TEXT,
                score_db_sql TEXT,
                score_ai_app TEXT,
                score_rag_sys TEXT,
                score_deployment TEXT,
                score INTEGER,
                reason TEXT,
                review_status INTEGER DEFAULT 0
            )
        ''')
        conn.commit()
    finally:
        conn.close()


def save_resume(resume_data):
    """
    將 main.py 整理好的 resume_data (Dict, 使用英文 Key) 寫入 SQLite 資料庫
    使用 SQLite 的 UPSERT (ON CONFLICT DO UPDATE)
    """
    conn = get_connection()

    columns = [
        "interview_state", "is_screened", "name", "code", "age",
        "total_work_years", "it_work_years", "autobiography", "work_experience",
        "highest_edu_level", "highest_edu_school", "highest_edu_major",
        "highest_edu_period", "second_edu_school", "second_edu_major",
        "tech_skills", "key_highlights", "notes",
        "score_data_eng", "score_db_sql", "score_ai_app",
        "score_rag_sys", "score_deployment", "score", "reason"
    ]

    values = []
    for col in columns:
        val = resume_data.get(col, "")
        if isinstance(val, list):
            val = ", ".join([str(v) for v in val])
        values.append(val)

    placeholders = ", ".join(["?"] * len(columns))
    update_parts = [f"{col} = excluded.{col}" for col in columns if col != "code"]
    update_clause = ", ".join(update_parts)

    sql = (
        f"INSERT INTO curriculum_vitae ({', '.join(columns)}) "
        f"VALUES ({placeholders}) "
        f"ON CONFLICT(code) DO UPDATE SET {update_clause}"
    )

    try:
        cursor = conn.cursor()
        cursor.execute(sql, values)
        conn.commit()
        print(f"   [DB] 已寫入資料庫: {resume_data.get('name', 'Unknown')}")
    except Exception as e:
        print(f"   [DB Error] 寫入失敗: {e}")
    finally:
        conn.close()


def delete_resume(code):
    """根據代碼刪除該筆資料 (用於排除解析失敗的資料)"""
    if not code:
        return
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM curriculum_vitae WHERE code = ?", (code,))
        conn.commit()
    except Exception as e:
        print(f"   [DB Error] 刪除失敗 ({code}): {e}")
    finally:
        conn.close()


def get_existing_codes():
    """獲取資料庫中所有已存在的代碼"""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT code FROM curriculum_vitae")
        rows = cursor.fetchall()
        return {row['code'] for row in rows if row['code']}
    except Exception as e:
        print(f"   [DB Error] 獲取代碼清單失敗: {e}")
        return set()
    finally:
        conn.close()
