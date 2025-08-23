async function callPredict(){
  const payload = {
    name: document.getElementById('name').value,
    dob: document.getElementById('dob').value,
    utc_iso: document.getElementById('utc').value,
    latitude: parseFloat(document.getElementById('lat').value),
    longitude: parseFloat(document.getElementById('lon').value),
    tone: document.getElementById('tone').value
  };
  const out = document.getElementById('out');
  out.textContent = 'Loading…';
  try {
    const res = await fetch('/api/v1/predict', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload)
    });
    const raw = await res.text();             // <- read as text first
    if (!res.ok) {                            // <- non-200? show raw
      out.textContent = `Server error (${res.status}):\n` + raw;
      return;
    }
    let data;
    try { data = JSON.parse(raw); }           // <- parse if it is JSON
    catch { out.textContent = `Non-JSON response:\n` + raw; return; }
    out.textContent = JSON.stringify(data, null, 2);
  } catch (e) {
    out.textContent = 'Network/JS error: ' + e;
  }
}
