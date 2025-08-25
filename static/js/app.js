// app/static/js/app.js (v5)
window.callPredict = async function () {
  const out = document.getElementById('out');
  if (out) out.textContent = 'Working...';

  const name = document.getElementById('name')?.value || null;
  const dob  = document.getElementById('dob')?.value;
  const utc  = document.getElementById('utc')?.value;
  const tone = document.getElementById('tone')?.value || 'Friendly';

  // READ hidden fields populated by the City dropdown
  const latStr = document.getElementById('latitude')?.value;
  const lonStr = document.getElementById('longitude')?.value;

  if (!dob || !utc) { out.textContent = 'Please enter DOB and UTC Birth ISO.'; return; }
  if (!latStr || !lonStr) { out.textContent = 'Please select Country → State → City.'; return; }

  const latitude  = parseFloat(latStr);
  const longitude = parseFloat(lonStr);
  if (Number.isNaN(latitude) || Number.isNaN(longitude)) { out.textContent = 'Coordinates invalid. Pick the city again.'; return; }

  const payload = { name, dob, utc_iso: utc, latitude, longitude, tone };

  try {
    const res = await fetch('/api/v1/predict', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const txt = await res.text();
    if (!res.ok) {
      out.textContent = `Server error (${res.status}): ${txt}`;
      return;
    }
    try { out.textContent = JSON.stringify(JSON.parse(txt), null, 2); }
    catch { out.textContent = txt; }
  } catch (e) {
    out.textContent = `Failed: ${e?.message || e}`;
  }
};
