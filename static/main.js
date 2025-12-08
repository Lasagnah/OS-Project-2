async function createRequest() {
  const name = document.getElementById('name').value || 'Anonymous';
  const priority = document.getElementById('priority').value;
  const est = document.getElementById('est_minutes').value || 60;
  const res = await fetch('/api/request', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({name: name, priority: priority, est_minutes: est})
  });
  if (res.ok) {
    document.getElementById('name').value = '';
    refreshAll();
  } else {
    alert('Failed to create request');
  }
}

async function refreshAll() {
  await Promise.all([loadResources(), loadAllocations(), loadQueue()]);
}

async function loadResources() {
  const res = await fetch('/api/resources');
  const list = await res.json();
  let html = '<table><tr><th>ID</th><th>Label</th><th>Type</th><th>Status</th></tr>';
  for (const r of list) {
    html += `<tr><td>${r.id}</td><td>${r.label}</td><td>${r.resource_type}</td><td>${r.status}</td></tr>`;
  }
  html += '</table>';
  document.getElementById('resources').innerHTML = html;
}

async function loadAllocations() {
  const res = await fetch('/api/allocations');
  const list = await res.json();
  let html = '<table><tr><th>Allocation ID</th><th>Request ID</th><th>Patient</th><th>Resource</th><th>Allocated At</th><th>Action</th></tr>';
  for (const a of list) {
    html += `<tr>
      <td>${a.id}</td>
      <td>${a.request_id}</td>
      <td>${a.name} (P${a.priority})</td>
      <td>${a.resource_type} #${a.resource_id}</td>
      <td>${a.allocated_at}</td>
      <td><button onclick="release(${a.id})">Release</button></td>
    </tr>`;
  }
  html += '</table>';
  document.getElementById('allocations').innerHTML = html;
}

async function loadQueue() {
  const res = await fetch('/api/requests');
  const list = await res.json();
  const queued = list.filter(r => r.status === 'queued');
  // compute waiting seconds client-side for display
  let html = '<table><tr><th>ID</th><th>Name</th><th>Priority</th><th>Requested At</th><th>Status</th></tr>';
  for (const r of queued) {
    html += `<tr>
      <td>${r.id}</td>
      <td>${r.name}</td>
      <td>${r.priority}</td>
      <td>${r.requested_at}</td>
      <td>${r.status}</td>
    </tr>`;
  }
  html += '</table>';
  if (queued.length === 0) html = '<em>No queued requests</em>';
  document.getElementById('queue').innerHTML = html;
}

async function release(allocation_id) {
  const res = await fetch('/api/release', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({allocation_id})
  });
  if (res.ok) refreshAll();
}

setInterval(refreshAll, 3000);
refreshAll();
