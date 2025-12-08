import sqlite3
import threading
import time
from datetime import datetime, timedelta
from flask import Flask, g, jsonify, request, render_template

DATABASE = 'hospital.db'
SCHEDULER_INTERVAL = 5  # seconds between allocation cycles
AGING_INTERVAL = 60     # seconds to reduce effective priority (aging)
MAX_PRIORITY = 1
MIN_PRIORITY = 5

RESOURCE_TYPES = {
    'ICU_BED': 3,
    'VENTILATOR': 2
}

app = Flask(__name__)
db_lock = threading.Lock()          # protects sqlite writes (shared resource)
allocation_lock = threading.Lock()  # protects in-memory allocation ops

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE, check_same_thread=False)
        db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def init_db():
    conn = sqlite3.connect(DATABASE)
    with open('schema.sql', 'r') as f:
        sql = f.read()
    conn.executescript(sql)
    conn.commit()
    conn.close()
    seed_resources()

def seed_resources():
    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) as c FROM resources")
    if cur.fetchone()[0] == 0:
        idx = 1
        for rtype, count in RESOURCE_TYPES.items():
            for i in range(count):
                cur.execute("INSERT INTO resources (resource_type, label, status) VALUES (?, ?, ?)",
                            (rtype, f"{rtype}-{idx}", "free"))
                idx += 1
        conn.commit()
    conn.close()

# Utility DB helpers
def db_execute(query, params=(), commit=False):
    with db_lock:
        conn = sqlite3.connect(DATABASE)
        cur = conn.cursor()
        cur.execute(query, params)
        if commit:
            conn.commit()
            last = cur.lastrowid
            conn.close()
            return last
        rows = cur.fetchall()
        conn.close()
        return rows

def db_query_rows(query, params=()):
    with db_lock:
        conn = sqlite3.connect(DATABASE)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(query, params)
        rows = cur.fetchall()
        conn.close()
        return rows

# API endpoints

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/request', methods=['POST'])
def create_request():
    data = request.json
    name = data.get('name', 'Anonymous')
    priority = int(data.get('priority', 3))
    est_minutes = int(data.get('est_minutes', 60))
    priority = max(MIN_PRIORITY, min(MAX_PRIORITY if False else priority, MIN_PRIORITY))  # ensure 1..5
    q = "INSERT INTO patient_requests (name, priority, est_minutes, status) VALUES (?, ?, ?, ?)"
    rid = db_execute(q, (name, priority, est_minutes, 'queued'), commit=True)
    return jsonify({"request_id": rid}), 201

@app.route('/api/requests', methods=['GET'])
def list_requests():
    rows = db_query_rows("SELECT * FROM patient_requests ORDER BY requested_at ASC")
    return jsonify([dict(r) for r in rows])

@app.route('/api/resources', methods=['GET'])
def list_resources():
    rows = db_query_rows("SELECT * FROM resources ORDER BY id")
    return jsonify([dict(r) for r in rows])

@app.route('/api/allocations', methods=['GET'])
def list_allocations():
    rows = db_query_rows("SELECT a.*, p.name, p.priority FROM allocations a JOIN patient_requests p ON p.id = a.request_id WHERE a.released_at IS NULL")
    return jsonify([dict(r) for r in rows])

@app.route('/api/release', methods=['POST'])
def release_allocation():
    data = request.json
    allocation_id = int(data.get('allocation_id'))
    with allocation_lock:
        # mark allocation released
        db_execute("UPDATE allocations SET released_at = CURRENT_TIMESTAMP WHERE id = ?", (allocation_id,), commit=True)
        # get the allocation row to know resource id
        rows = db_query_rows("SELECT resource_id, request_id FROM allocations WHERE id = ?", (allocation_id,))
        if rows:
            res_id = rows[0]['resource_id']
            req_id = rows[0]['request_id']
            db_execute("UPDATE resources SET status = 'free' WHERE id = ?", (res_id,), commit=True)
            db_execute("UPDATE patient_requests SET status = 'completed', released_at = CURRENT_TIMESTAMP WHERE id = ?", (req_id,), commit=True)
    return jsonify({"status": "released"})

# Scheduler core
def scheduler_loop():
    print("[Scheduler] started")
    while True:
        try:
            run_allocation_cycle()
        except Exception as e:
            print("[Scheduler] error:", e)
        time.sleep(SCHEDULER_INTERVAL)

def effective_priority(original_priority, waiting_seconds):
    """
    Aging: every AGING_INTERVAL seconds of waiting improves effective priority by 1 (towards 1).
    Lower number => higher priority.
    """
    bonus = waiting_seconds // AGING_INTERVAL
    effective = max(1, original_priority - int(bonus))
    return effective

def run_allocation_cycle():
    with allocation_lock:
        now = datetime.utcnow()
        # 1) find free resources
        free_resources = db_query_rows("SELECT * FROM resources WHERE status = 'free' ORDER BY resource_type, id")
        if not free_resources:
            return

        # 2) find queued requests
        rows = db_query_rows("SELECT * FROM patient_requests WHERE status = 'queued' ORDER BY requested_at ASC")
        queued = []
        for r in rows:
            req_time = datetime.strptime(r['requested_at'], "%Y-%m-%d %H:%M:%S")
            waiting = (now - req_time).total_seconds()
            eff = effective_priority(r['priority'], waiting)
            queued.append({
                'id': r['id'],
                'name': r['name'],
                'priority': r['priority'],
                'effective_priority': eff,
                'waiting': waiting,
                'requested_at': r['requested_at'],
                'est_minutes': r['est_minutes']
            })
        if not queued:
            return

        # 3) sort queued by effective_priority then FIFO
        queued.sort(key=lambda x: (x['effective_priority'], x['requested_at']))

        # 4) allocate: try to match resource types in round-robin or all-purpose assignment
        # For simplicity, assume all requests can use any ICU_BED resource for now.
        for req in queued:
            if not free_resources:
                break
            # choose a free resource (simple: first free)
            chosen = free_resources.pop(0)
            # perform allocation
            db_execute("INSERT INTO allocations (request_id, resource_type, resource_id) VALUES (?, ?, ?)",
                       (req['id'], chosen['resource_type'], chosen['id']), commit=True)
            db_execute("UPDATE resources SET status = 'in_use' WHERE id = ?", (chosen['id'],), commit=True)
            db_execute("UPDATE patient_requests SET status = 'allocated', allocated_at = CURRENT_TIMESTAMP WHERE id = ?", (req['id'],), commit=True)
            print(f"[Scheduler] Allocated req {req['id']} -> resource {chosen['label']}")

# start scheduler thread on app start
def start_scheduler_in_background():
    t = threading.Thread(target=scheduler_loop, daemon=True)
    t.start()

if __name__ == '__main__':
    import os
    if not os.path.exists(DATABASE):
        init_db()
    else:
        # ensure resources seeded if DB exists but empty
        seed_resources()
    start_scheduler_in_background()
    app.run(debug=True, threaded=True)
