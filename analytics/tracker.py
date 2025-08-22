import sqlite3, time, os, json, threading, requests
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / 'analytics.db'
DB_PATH = str(DB_PATH)

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_type TEXT,
        payload TEXT,
        created_at INTEGER
    )""")
    conn.commit(); conn.close()

init_db()

GA4_MEASUREMENT_ID = os.getenv('GA4_MEASUREMENT_ID', '')
GA4_API_SECRET = os.getenv('GA4_API_SECRET', '')
GA4_CLIENT_ID = 'vedic_demo_client'

def record_event(event_type: str, payload: dict):
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute('INSERT INTO events (event_type,payload,created_at) VALUES (?,?,?)',
                    (event_type, json.dumps(payload), int(time.time())))
        conn.commit(); conn.close()
    except Exception as e:
        print('Analytics write error:', e)

def _send_to_ga(event_type, payload):
    if not GA4_MEASUREMENT_ID or not GA4_API_SECRET: return
    url = f'https://www.google-analytics.com/mp/collect?measurement_id={GA4_MEASUREMENT_ID}&api_secret={GA4_API_SECRET}'
    data = {'client_id': GA4_CLIENT_ID, 'events': [{'name': event_type, 'params': payload}]}
    try: requests.post(url, json=data, timeout=2)
    except Exception as e: print('GA send error:', e)

def record_event_with_ga(event_type: str, payload: dict):
    record_event(event_type, payload)
    threading.Thread(target=_send_to_ga, args=(event_type, payload), daemon=True).start()

def query_summary():
    conn = sqlite3.connect(DB_PATH); cur = conn.cursor()
    cur.execute('SELECT COUNT(*), MIN(created_at), MAX(created_at) FROM events')
    total, first_ts, last_ts = cur.fetchone()
    cur.execute('SELECT event_type, COUNT(*) FROM events GROUP BY event_type')
    by_type = cur.fetchall()
    conn.close()
    return {'total_events': total or 0, 'first_ts': first_ts, 'last_ts': last_ts, 'by_type': by_type}
