"use client";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { tutorAuth } from "../lib/firebase";
import { pagePoint, selectionBox, validBox, type Box, type Point } from "../lib/page-coordinates";

type Assessment = { id: string; filename: string; page_count: number; state: string };
export type Page = { id: string; page_number: number; width: number; height: number; rotation: number; candidates: { id: string; label: string; bbox: Box }[] };
async function authorized(path: string, signal: AbortSignal, init: RequestInit = {}) {
  const user = (await tutorAuth()).currentUser;
  if (!user) throw new Error("Sign-in required");
  const headers = new Headers(init.headers); headers.set("Authorization", `Bearer ${await user.getIdToken()}`);
  return fetch(`/api/assessments${path}`, { ...init, headers, cache: "no-store", signal });
}
const button = "rounded-lg border border-emerald-900/25 px-4 py-2 disabled:opacity-40";
export function AssessmentWorkspace() {
  const [items, setItems] = useState<Assessment[]>([]);
  const [active, setActive] = useState<Assessment | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [kind, setKind] = useState("unknown");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const key = useRef("");
  const fileInput = useRef<HTMLInputElement>(null);
  const requests = useRef(new Set<AbortController>());
  const request = useCallback(async (path: string, init: RequestInit = {}) => {
    const controller = new AbortController(); requests.current.add(controller);
    try { const response = await authorized(path, controller.signal, init); return new Response(await response.arrayBuffer(), { status: response.status, headers: response.headers }); }
    finally { requests.current.delete(controller); }
  }, []);
  const refresh = useCallback(async () => {
    const response = await request(""); if (!response.ok) throw new Error();
    setItems((await response.json()).assessments);
  }, [request]);
  useEffect(() => {
    const outstanding = requests.current;
    const timer = setTimeout(() => refresh().catch(() => setMessage("Unable to load recent assessments. Try refreshing.")), 0);
    return () => { clearTimeout(timer); outstanding.forEach(c => c.abort()); outstanding.clear(); };
  }, [refresh]);
  async function upload(event: FormEvent) {
    event.preventDefault(); if (!file) return;
    setBusy(true); setMessage("");
    try {
      if (!file.name.toLowerCase().endsWith(".pdf") || !file.size || file.size > 25 * 1024 * 1024) { setMessage("Choose a PDF no larger than 25 MB."); return; }
      key.current ||= crypto.randomUUID();
      const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
      const sha256 = Array.from(new Uint8Array(digest), b => b.toString(16).padStart(2, "0")).join("");
      const form = new FormData();
      form.set("file", new File([file], file.name, { type: "application/pdf" }));
      form.set("metadata", JSON.stringify({ filename: file.name, media_type: "application/pdf", size_bytes: file.size, sha256, assessment_type: kind }));
      const response = await request("/upload", { method: "POST", headers: { "Idempotency-Key": key.current }, body: form });
      if (!response.ok) {
        const messages: Record<number, string> = { 413: "The PDF exceeds the 25 MB limit.", 415: "Choose a PDF file.", 422: "This PDF cannot be accepted. Check that it opens normally, has at most 200 pages, and has no password, scripts or attachments.", 409: "This upload conflicts with an earlier attempt. Choose the file again to start a new upload.", 429: "Uploads are busy. Please retry shortly.", 401: "Please sign in again." };
        setMessage(messages[response.status] ?? "Upload was interrupted. Retry with the same file; your upload will not be duplicated."); return;
      }
      const accepted = await response.json();
      setActive({ id: accepted.resource_id, filename: file.name, page_count: 0, state: accepted.status });
      await refresh(); setFile(null); if (fileInput.current) fileInput.current.value = ""; key.current = "";
    } catch { setMessage("Upload was interrupted. Retry with the same file; your upload will not be duplicated."); }
    finally { setBusy(false); }
  }
  return <div className="mt-8 border-t border-slate-200 pt-6">
    <h3 className="text-xl font-semibold">Your assessments</h3>
    <p className="mt-2 text-sm text-slate-600">Upload your work to view its pages and locate questions. Analysis and marking review come later.</p>
    <form onSubmit={upload} className="mt-5 grid gap-4 sm:grid-cols-2">
      <label className="grid gap-2 text-sm font-medium">PDF file<input ref={fileInput} type="file" accept=".pdf,application/pdf" disabled={busy} onChange={e => { setFile(e.target.files?.[0] ?? null); key.current = ""; setMessage(""); }} className="min-w-0 rounded-lg border border-slate-300 p-3" /></label>
      <label className="grid gap-2 text-sm font-medium">Kind of work<select value={kind} disabled={busy} onChange={e => { setKind(e.target.value); key.current = ""; }} className="rounded-lg border border-slate-300 p-3"><option value="unknown">Not sure yet</option><option value="marked_test">Marked test</option><option value="ordinary_homework">Homework</option><option value="exam">Exam</option><option value="IB_math_IA">IB Math IA</option></select></label>
      <div className="sm:col-span-2 flex flex-wrap items-center gap-4"><button disabled={busy || !file} className="rounded-lg bg-emerald-900 px-5 py-3 text-white disabled:opacity-40">{busy ? "Uploading…" : "Upload PDF"}</button><p className="text-sm text-slate-600">Up to 25 MB · 200 pages · Private to you</p></div>
    </form>
    {message && <p role="alert" className="mt-4 text-red-800">{message}</p>}
    <div className="mt-6"><div className="flex items-center justify-between"><h4 className="font-medium">Recent assessments</h4><button className={button} onClick={() => refresh().catch(() => setMessage("Unable to refresh assessments."))}>Refresh</button></div>
      {!items.length && <p className="mt-3 text-sm text-slate-500">Your uploaded work will appear here.</p>}
      <ul className="mt-3 grid gap-2">{items.map(item => <li key={item.id}><button onClick={() => setActive(item)} className={`w-full rounded-lg border px-4 py-3 text-left ${active?.id === item.id ? "border-emerald-800 bg-emerald-50" : "border-slate-200"}`}><span className="break-words font-medium">{item.filename}</span><span className="ml-3 text-sm text-slate-500">{item.page_count} pages</span></button></li>)}</ul>
    </div>
    {active && <PageViewer key={active.id} assessment={active} onReady={refresh} />}
  </div>;
}
function PageViewer({ assessment, onReady }: { assessment: Assessment; onReady: () => Promise<void> }) {
  const [pages, setPages] = useState<Page[]>([]);
  const [index, setIndex] = useState(0);
  const [state, setState] = useState("Preparing pages…");
  const [failure, setFailure] = useState(false);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    const controller = new AbortController(); let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const response = await authorized(`/${assessment.id}/pages`, controller.signal);
        if (!response.ok) throw new Error();
        const data = await response.json();
        if (data.pages.length) { setPages(data.pages); setState(""); await onReady(); return; }
        const status = await authorized(`/${assessment.id}/status`, controller.signal);
        if (!status.ok) throw new Error();
        const job = await status.json();
        if (["failed", "cancelled"].includes(job.status)) { setFailure(true); setState("Pages could not be prepared. Try a smaller PDF or contact the maintainer."); return; }
        timer = setTimeout(poll, 1500);
      } catch { if (!controller.signal.aborted) { setFailure(true); setState("Unable to load this assessment. Retry when the connection is available."); } }
    }
    (async () => {
      try {
        const response = await authorized(`/${assessment.id}/render`, controller.signal, { method: "POST" });
        if (!response.ok) throw new Error(); await poll();
      } catch { if (!controller.signal.aborted) { setFailure(true); setState("Unable to prepare pages. Please retry."); } }
    })();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [assessment.id, onReady, retry]);
  const page = pages[index];
  return <section className="mt-8 rounded-xl border border-emerald-900/20 bg-slate-50 p-4" aria-label="Assessment viewer">
    <h4 className="break-words text-lg font-semibold">{assessment.filename}</h4>
    {state && <p role={failure ? "alert" : "status"} className="mt-3">{state}</p>}
    {failure && <button className={`${button} mt-3`} onClick={() => { setFailure(false); setState("Preparing pages…"); setRetry(n => n + 1); }}>Retry loading</button>}
    {page && <><div className="my-4 flex flex-wrap items-center gap-3"><button className={button} disabled={index === 0} onClick={() => setIndex(i => i - 1)}>Previous page</button><label className="text-sm">Page <select value={index} onChange={e => setIndex(Number(e.target.value))} className="rounded border p-2">{pages.map((p, i) => <option value={i} key={p.id}>{p.page_number}</option>)}</select> of {pages.length}</label><button className={button} disabled={index === pages.length - 1} onClick={() => setIndex(i => i + 1)}>Next page</button></div><PageCanvas key={page.id} assessmentId={assessment.id} page={page} /></>}
  </section>;
}
export function PageCanvas({ assessmentId, page, imagePath, onSelect, initialBox, annotationMode = false, lockSelection = false }: { assessmentId: string; page: Page; imagePath?: string; onSelect?: (box: Box | null) => void; initialBox?: Box; annotationMode?: boolean; lockSelection?: boolean }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const start = useRef<Point | null>(null);
  const [box, setBox] = useState<Box | null>(initialBox ?? null);
  function selectBox(value: Box | null) { setBox(value); onSelect?.(value); }
  const [zoom, setZoom] = useState("fit");
  const [error, setError] = useState("");
  const [loaded, setLoaded] = useState(false);
  useEffect(() => {
    const controller = new AbortController(); let url = "";
    (async () => {
      try {
        const response = imagePath ? await fetch(imagePath, { headers: { Authorization: `Bearer ${await (await tutorAuth()).currentUser?.getIdToken()}` }, signal: controller.signal, cache: "no-store" }) : await authorized(`/${assessmentId}/pages/${page.page_number}/image`, controller.signal);
        if (!response.ok) throw new Error(); url = URL.createObjectURL(await response.blob());
        const image = new Image(); image.src = url; await image.decode();
        if (!controller.signal.aborted && canvas.current) { canvas.current.width = page.width; canvas.current.height = page.height; canvas.current.getContext("2d")?.drawImage(image, 0, 0); setLoaded(true); }
      } catch { if (!controller.signal.aborted) setError("Unable to load this page. Switch pages to retry."); }
      finally { if (url) URL.revokeObjectURL(url); }
    })();
    return () => { controller.abort(); if (url) URL.revokeObjectURL(url); };
  }, [assessmentId, page, imagePath]);
  function pointer(event: React.PointerEvent<HTMLDivElement>) { return pagePoint(event.clientX, event.clientY, event.currentTarget.getBoundingClientRect(), page.width, page.height); }
  function locate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const data = new FormData(event.currentTarget);
    const value = { x: Number(data.get("x")), y: Number(data.get("y")), width: Number(data.get("width")), height: Number(data.get("height")) };
    if (validBox(value, page.width, page.height)) { selectBox(value); setError(""); } else setError("Keep the area inside this page, with positive width and height.");
  }
  return <>
    <div className="mb-3 flex flex-wrap items-center justify-between gap-3"><p className="text-sm text-slate-600">{lockSelection ? "The source box is fixed while editing notes." : "Drag across a question to locate its area."}</p><label className="text-sm">Zoom <select className="rounded border p-2" value={zoom} onChange={e => setZoom(e.target.value)}><option value="fit">Fit width</option>{[50, 75, 100, 150, 200].map(z => <option key={z} value={z}>{z}%</option>)}</select></label></div>
    {error && <p role="alert" className="my-3 text-red-800">{error}</p>}
    {!loaded && !error && <p role="status">Loading page…</p>}
    <div className="overflow-auto rounded-lg border border-slate-300 bg-slate-200 p-2">
      <div className="relative bg-white" style={{ width: zoom === "fit" ? "100%" : page.width * Number(zoom) / 100, aspectRatio: `${page.width}/${page.height}`, touchAction: "none", cursor: "crosshair" }}
        onPointerDown={event => { if (!loaded || lockSelection) return; start.current = pointer(event); event.currentTarget.setPointerCapture(event.pointerId); selectBox(null); }}
        onPointerMove={event => { if (start.current) setBox(selectionBox(start.current, pointer(event))); }}
        onPointerUp={event => { if (start.current) { const value = selectionBox(start.current, pointer(event)); selectBox(validBox(value, page.width, page.height) ? value : null); start.current = null; } }} onPointerCancel={() => { start.current = null; selectBox(null); }}>
        <canvas ref={canvas} className="block h-full w-full" aria-label={`PDF page ${page.page_number}. Use the coordinate form below to locate an area with a keyboard.`} />
        <svg className="pointer-events-none absolute inset-0 h-full w-full" viewBox={`0 0 ${page.width} ${page.height}`}>
          {box && <rect x={box.x} y={box.y} width={box.width} height={box.height} fill="#05966922" stroke="#047857" strokeWidth={3} />}
        </svg>
      </div>
    </div>
    <div className="mt-4"><p className="text-sm font-medium">Question navigation hints</p><p className="mt-1 text-xs text-slate-500">These are possible numbered prompts, not verified questions. Scanned pages may have no hints.</p><div className="mt-2 flex flex-wrap gap-2">{page.candidates.map(candidate => <button key={candidate.id} className={button} disabled={lockSelection} onClick={() => { selectBox(candidate.bbox); setError(""); }}>{candidate.label}</button>)}{!page.candidates.length && <p className="text-sm text-slate-500">Select a question area directly on the page.</p>}</div></div>
    <p className="mt-4 text-sm" aria-live="polite">{box ? `Page ${page.page_number} · x ${box.x.toFixed(1)}, y ${box.y.toFixed(1)} · width ${box.width.toFixed(1)}, height ${box.height.toFixed(1)}` : `Page ${page.page_number} · ${page.width} × ${page.height} coordinates`}</p>
    <form onSubmit={locate} className="mt-3 flex flex-wrap items-end gap-2">{["x", "y", "width", "height"].map(field => <label className="grid gap-1 text-xs capitalize" key={field}>{field}<input key={box ? box[field as keyof Box].toFixed(1) : "empty"} defaultValue={box?.[field as keyof Box].toFixed(1) ?? ""} name={field} disabled={lockSelection} type="number" step="0.1" min="0" required className="w-20 rounded border border-slate-300 bg-white p-2" /></label>)}<button className={button} disabled={!loaded || lockSelection}>Locate area</button><button type="button" className={button} disabled={lockSelection} onClick={() => selectBox(null)}>Clear</button></form>
    <p className="mt-3 text-xs text-slate-500">{annotationMode ? "Select a source area, then save its annotation below." : "Selections are a temporary viewing aid. Saving annotations arrives in the next step."}</p>
  </>;
}
