import { useState } from 'react';
import { uploadVideo, videoUrl, fetchRoi } from './api.js';

export default function App() {
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);
  const [roiSummary, setRoiSummary] = useState(null);

  async function onUpload(e) {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    setError(null);
    setResult(null);
    setRoiSummary(null);
    try {
      const data = await uploadVideo(file);
      setResult(data);
      // Fire-and-forget secondary fetch; primarily a sanity check that
      // the metadata endpoint matches the spec for this video.
      fetchRoi(data.video_id)
        .then((roi) => setRoiSummary(roi.rois.length))
        .catch(() => {});
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="container">
      <h1>Face ROI Video</h1>
      <p className="subtitle">
        Upload a short MP4. The server detects one face per frame, draws
        a bounding box, and returns the processed clip.
      </p>

      <form onSubmit={onUpload} className="card">
        <input
          type="file"
          accept="video/mp4"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          disabled={busy}
        />
        <button type="submit" disabled={!file || busy}>
          {busy ? 'Processing…' : 'Upload & Process'}
        </button>
      </form>

      {error && <div className="error">{error}</div>}

      {result && (
        <section className="card">
          <h2>Result</h2>
          <ul className="meta">
            <li><strong>Video ID:</strong> {result.video_id}</li>
            <li><strong>Frames:</strong> {result.frame_count}</li>
            <li><strong>FPS:</strong> {result.fps.toFixed(2)}</li>
            <li><strong>Faces detected:</strong> {result.roi_count}</li>
            {roiSummary !== null && (
              <li><strong>ROI rows in DB:</strong> {roiSummary}</li>
            )}
          </ul>
          {result.warning && <div className="warning">{result.warning}</div>}
          <video
            controls
            src={videoUrl(result.video_id)}
            style={{ width: '100%', marginTop: '1rem' }}
          />
        </section>
      )}
    </main>
  );
}
