// static/main.js
const dashboardBody = document.getElementById('dashboard-body');
const btnRefresh = document.getElementById('btn-refresh');

async function fetchAndRender() {
  try {
    const resp = await fetch('/api/check_all', { method: 'POST' });
    const data = await resp.json();
    const ips = data.ips || [];
    if (!dashboardBody) return;
    dashboardBody.innerHTML = '';
    ips.forEach(ip => {
      const tr = document.createElement('tr');
      tr.className = ip.last_status === 'down' ? 'down' : 'up';

      const tdIp = document.createElement('td');
      const a = document.createElement('a');
      a.href = `/ip/${ip.id}`;
      a.target = '_blank';
      a.textContent = ip.ip;
      tdIp.appendChild(a);

      const tdName = document.createElement('td'); tdName.textContent = ip.name || '-';
      const tdType = document.createElement('td'); tdType.textContent = ip.device_type || '-';
      const tdImp = document.createElement('td'); tdImp.textContent = ip.importance || '-';

      const tdStatus = document.createElement('td'); tdStatus.className = 'status'; tdStatus.textContent = ip.last_status || '-';
      const tdPing = document.createElement('td'); tdPing.textContent = ip.last_ping_ms === null ? '-' : ip.last_ping_ms;
      const td5 = document.createElement('td'); td5.className = ip.last5 < 95 ? 'bad' : 'good'; td5.textContent = ip.last5 + '%';
      const td60 = document.createElement('td'); td60.className = ip.last60 < 95 ? 'bad' : 'good'; td60.textContent = ip.last60 + '%';
      const tdChecked = document.createElement('td'); tdChecked.textContent = ip.last_checked ? new Date(ip.last_checked).toLocaleString() : '-';

      tr.appendChild(tdIp);
      tr.appendChild(tdName);
      tr.appendChild(tdType);
      tr.appendChild(tdImp);
      tr.appendChild(tdStatus);
      tr.appendChild(tdPing);
      tr.appendChild(td5);
      tr.appendChild(td60);
      tr.appendChild(tdChecked);

      dashboardBody.appendChild(tr);
    });
  } catch (err) {
    console.error('Error fetching statuses', err);
  }
}

// Initial render on load (server already provided initial data; we also trigger an immediate check to refresh)
window.addEventListener('load', () => {
  // Trigger an on-demand check and render
  fetchAndRender();
});

// Manual refresh
if (btnRefresh) btnRefresh.addEventListener('click', fetchAndRender);

// Auto refresh every 30 seconds
setInterval(fetchAndRender, 30000);
