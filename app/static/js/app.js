async function callPredict() {
  const out = document.getElementById('out');
  out.textContent = 'Working...';

  const payload = {
    name: document.getElementById('name').value || null,
    dob: document.getElementById('dob').value,
    utc_iso: document.getElementById('utc').value,
    latitude: parseFloat(document.getElementById('latitude').value),
    longitude: parseFloat(document.getElementById('longitude').value),
    tone: document.getElementById('tone').value
  };

  if (Number.isNaN(payload.latitude) || Number.isNaN(payload.longitude)) {
    out.textContent = 'Please select Country → State → City (to set coordinates).';
    return;
  }

  const res = await fetch('/api/v1/predict', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify(payload)
  });
  out.textContent = JSON.stringify(await res.json(), null, 2);
}

