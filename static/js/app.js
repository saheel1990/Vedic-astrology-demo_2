async function callPredict() {
  const out = document.getElementById('out');
  out.textContent = 'Working...';

  const name = document.getElementById('name').value || null;
  const dob = document.getElementById('dob').value;
  const utc = document.getElementById('utc').value;
  const tone = document.getElementById('tone').value;

  // NEW: read from hidden fields that the dropdowns fill
  const latStr = document.getElementById('latitude').value;
  const lonStr = document.getElementById('longitude').value;
  const lat = parseFloat(latStr), lon = parseFloat(lonStr);

  if (!dob || !utc) {
    out.textContent = 'Please enter DOB and UTC Birth ISO.';
    return;
  }
  if (Number.isNaN(lat) || Number.isNaN(lon)) {
    out.textContent = 'Please select Country → State → City so we can set latitude/longitude.';
    return;
  }

  const payload = {
    name,
    dob,
    utc_iso: utc,      // backend expects utc_iso
    latitude: lat,
    longitude: lon,
    tone
  };

  try {
    const res = await fetch('/api/v1/predict', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    out.textContent = JSON.stringify(data, null, 2);
  } catch (e) {
    out.textContent = `Failed: ${e}`;
  }
}
