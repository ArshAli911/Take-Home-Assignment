// Both dev (Vite proxy) and prod (nginx) serve the API under /api,
// so we use a single relative base.
const API_BASE = '/api';

export async function uploadVideo(file) {
  const form = new FormData();
  form.append('file', file);
  const res = await fetch(`${API_BASE}/upload`, { method: 'POST', body: form });
  if (!res.ok) {
    const detail = await safeDetail(res);
    throw new Error(detail || `Upload failed (${res.status})`);
  }
  return res.json();
}

export function videoUrl(videoId) {
  return `${API_BASE}/video/${videoId}`;
}

export async function fetchRoi(videoId) {
  const res = await fetch(`${API_BASE}/roi/${videoId}`);
  if (!res.ok) {
    throw new Error(`Failed to load ROI (${res.status})`);
  }
  return res.json();
}

async function safeDetail(res) {
  try {
    const body = await res.json();
    return body.detail || JSON.stringify(body);
  } catch {
    return null;
  }
}
