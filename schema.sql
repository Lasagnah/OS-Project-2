CREATE TABLE IF NOT EXISTS patient_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    priority INTEGER NOT NULL, -- 1 (highest) .. 5 (lowest)
    est_minutes INTEGER NOT NULL,
    status TEXT NOT NULL, -- queued, allocated, completed, cancelled
    requested_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    allocated_at DATETIME,
    released_at DATETIME
);

CREATE TABLE IF NOT EXISTS allocations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id INTEGER NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id INTEGER NOT NULL,
    allocated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    released_at DATETIME,
    FOREIGN KEY(request_id) REFERENCES patient_requests(id)
);

CREATE TABLE IF NOT EXISTS resources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    resource_type TEXT NOT NULL, -- example: ICU_BED, VENTILATOR
    label TEXT NOT NULL, -- human label like "ICU-1"
    status TEXT NOT NULL -- free, in_use, out_of_service
);
