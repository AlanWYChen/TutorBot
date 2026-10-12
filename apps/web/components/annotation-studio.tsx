"use client";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { AnnotationDatasets } from "./annotation-datasets";
import { tutorAuth } from "../lib/firebase";
import { PageCanvas, type Page } from "./assessment-workspace";
import type { Box } from "../lib/page-coordinates";

type Source = { id: string; filename: string; page_count: number };
type Annotation = { id: string; page_number: number; bbox: Box; revision: number; question: string; response: string; marks_awarded: number | null; marks_possible: number | null; first_error: string; observed_behaviours: string; observation_status: string; intervention: string; rationale: string };
const button = "rounded-lg border border-emerald-900/25 px-4 py-2 disabled:opacity-40";
async function api(path: string, signal: AbortSignal, init: RequestInit = {}) {
  const user = (await tutorAuth()).currentUser; if (!user) throw new Error();
  const headers = new Headers(init.headers); headers.set("Authorization", `Bearer ${await user.getIdToken()}`);
  return fetch(`/api/studio/${path}`, { ...init, headers, signal, cache: "no-store" });
}
export function AnnotationStudio() {
  const [sources, setSources] = useState<Source[]>([]);
  const [active, setActive] = useState<Source | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const controller = useRef<AbortController | null>(null);
  const key = useRef("");
  const refresh = useCallback(async (signal: AbortSignal) => { const response = await api("sources", signal); if (!response.ok) throw new Error(); setSources((await response.json()).documents); }, []);
  useEffect(() => { const c = new AbortController(); controller.current = c; const timer = setTimeout(() => refresh(c.signal).catch(() => { if (!c.signal.aborted) setMessage("Unable to load sources."); }), 0); return () => { clearTimeout(timer); c.abort(); }; }, [refresh]);
  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = event.currentTarget; const values = new FormData(form);
    const file = values.get("file") as File; const signal = controller.current!.signal;
    setBusy(true); setMessage("");
    try {
      if (!file?.size || file.size > 25*1024*1024 || !file.name.toLowerCase().endsWith(".pdf")) { setMessage("Choose a PDF up to 25 MB."); return; }
      const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
      const metadata = { filename: file.name, media_type: "application/pdf", size_bytes: file.size, sha256: Array.from(new Uint8Array(digest), b => b.toString(16).padStart(2,"0")).join(""), title: values.get("title"), author: values.get("author"), publisher: values.get("publisher"), kind: "reference", source_authority: "supplemental", license_metadata: { rights: values.get("rights") } };
      key.current ||= crypto.randomUUID(); const body = new FormData(); body.set("file", new File([file], file.name, { type: "application/pdf" })); body.set("metadata", JSON.stringify(metadata));
      const response = await api("upload", signal, { method: "POST", headers: { "Idempotency-Key": key.current }, body });
      if (!response.ok) { setMessage(response.status === 422 ? "Check the source details and PDF safeguards." : "Upload failed. Retry unchanged details to avoid duplicates."); return; }
      const data = await response.json(); setActive({ id: data.resource_id, filename: file.name, page_count: 0 }); await refresh(signal); form.reset(); key.current = "";
    } catch { if (!signal.aborted) setMessage("Upload interrupted. Retry unchanged details."); } finally { setBusy(false); }
  }
  return <div className="mt-8 border-t border-slate-200 pt-6"><h3 className="text-xl font-semibold">Annotation studio</h3><p className="mt-2 text-sm text-slate-600">Work from authorized maintainer sources. Student accounts and private uploads are not accessible here. Sources and notes stay draft.</p>
    <form onSubmit={upload} onChange={() => { key.current = ""; }} className="mt-5 grid gap-3 sm:grid-cols-2">
      <label className="grid gap-1 text-sm">Source PDF<input name="file" type="file" accept=".pdf,application/pdf" required disabled={busy} className="min-w-0 rounded border p-2" /></label>
      {["title", "author", "publisher", "rights"].map(name => <label key={name} className="grid gap-1 text-sm capitalize">{name === "rights" ? "License or permission note" : name}<input name={name} maxLength={256} required disabled={busy} className="rounded border p-2" /></label>)}
      <label className="flex items-center gap-2 text-sm sm:col-span-2"><input type="checkbox" required disabled={busy} />I have permission to use this reference or synthetic teaching example.</label>
      <button disabled={busy} className="rounded bg-emerald-900 px-4 py-3 text-white disabled:opacity-40">{busy ? "Uploading…" : "Upload source"}</button>
    </form>{message && <p role="alert" className="mt-3 text-red-800">{message}</p>}
    <div className="mt-5 flex items-center justify-between"><h4 className="font-medium">Your source documents</h4><button className={button} onClick={() => refresh(controller.current!.signal).catch(() => setMessage("Unable to refresh sources."))}>Refresh sources</button></div>
    <ul className="mt-3 grid gap-2">{sources.map(source => <li key={source.id}><button className={`${button} w-full text-left`} onClick={() => setActive(source)}>{source.filename} · {source.page_count} pages</button></li>)}</ul>
    {active && <SourceEditor key={active.id} source={active} />}
    <AnnotationDatasets sources={sources} />
  </div>;
}
function SourceEditor({ source }: { source: Source }) {
  const [pages, setPages] = useState<Page[]>([]); const [index, setIndex] = useState(0);
  const [notes, setNotes] = useState<Annotation[]>([]); const [editing, setEditing] = useState<Annotation | null>(null);
  const [box, setBox] = useState<Box | null>(null); const [message, setMessage] = useState("Preparing source pages…");
  const control = useRef<AbortController | null>(null);
  const [signal, setSignal] = useState<AbortSignal | null>(null);
  const reloadNotes = useCallback(async (signal: AbortSignal) => { const response = await api(`sources/${source.id}/annotations`, signal); if (!response.ok) throw new Error(); setNotes((await response.json()).annotations); }, [source.id]);
  useEffect(() => { const c = new AbortController(); control.current = c; let timer: ReturnType<typeof setTimeout>;
    async function poll() { try { const response = await api(`sources/${source.id}/pages`, c.signal); if (!response.ok) throw new Error(); const data = await response.json(); if (data.pages.length) { setSignal(c.signal); setPages(data.pages); setMessage(""); await reloadNotes(c.signal); return; } const status = await api(`sources/${source.id}/status`, c.signal); const job = await status.json(); if (["failed", "cancelled"].includes(job.status)) { setMessage("Source rendering failed. Try a smaller PDF."); return; } timer = setTimeout(poll, 1500); } catch { if (!c.signal.aborted) setMessage("Unable to load source pages."); } }
    api(`sources/${source.id}/render`, c.signal, { method: "POST" }).then(response => { if (!response.ok) throw new Error(); return poll(); }).catch(() => { if (!c.signal.aborted) setMessage("Unable to prepare this source."); });
    return () => { c.abort(); clearTimeout(timer); };
  }, [source.id, reloadNotes]);
  const page = pages[index];
  return <section className="mt-6 rounded-xl border bg-slate-50 p-4" aria-label="Source annotation editor"><h4 className="text-lg font-semibold">{source.filename}</h4>{message && <p role="status" className="mt-3">{message}</p>}
    {page && signal && <><div className="my-4 flex flex-wrap items-center gap-3"><label>Source page <select value={index} onChange={e => { setIndex(Number(e.target.value)); setBox(null); setEditing(null); }} className="rounded border p-2">{pages.map((p,i) => <option key={p.id} value={i}>{p.page_number}</option>)}</select> of {pages.length}</label><button className={button} onClick={() => { setEditing(null); setBox(null); }}>New annotation</button></div>
      <PageCanvas key={`${page.id}/${editing?.id ?? "new"}`} assessmentId={source.id} page={page} imagePath={`/api/studio/sources/${source.id}/pages/${page.page_number}/image`} annotationMode lockSelection={!!editing} initialBox={editing?.bbox} onSelect={value => { if (!editing) setBox(value); }} />
      <AnnotationForm key={`${editing?.id ?? "new"}/${editing?.revision ?? 0}/${page.id}`} source={source} page={page} box={editing?.bbox ?? box} existing={editing} signal={signal} onSaved={async note => { await reloadNotes(control.current!.signal); setEditing(note); setBox(note.bbox); }} />
    </>}
    <div className="mt-6"><div className="flex items-center justify-between"><h5 className="font-medium">Saved annotations</h5><button className={button} onClick={() => reloadNotes(control.current!.signal).catch(() => setMessage("Unable to reload annotations."))}>Reload annotations</button></div><p className="mt-1 text-xs text-slate-600">Editing updates the notes; the original source box and crop remain fixed.</p><ul className="mt-3 grid gap-2">{notes.map(note => <li key={note.id}><button className={`${button} w-full text-left`} onClick={() => { setIndex(pages.findIndex(p => p.page_number === note.page_number)); setEditing(note); setBox(note.bbox); }}>Page {note.page_number} · {note.question.slice(0,100)} · revision {note.revision}</button></li>)}</ul></div>
  </section>;
}
function AnnotationForm({ source, page, box, existing, signal, onSaved }: { source: Source; page: Page; box: Box | null; existing: Annotation | null; signal: AbortSignal; onSaved: (note: Annotation) => Promise<void> }) {
  const [busy,setBusy] = useState(false); const [message,setMessage] = useState(""); const key = useRef(crypto.randomUUID());
  const canvas = useRef<HTMLCanvasElement>(null);
  useEffect(() => { let url = ""; const c = new AbortController(); if (existing) api(`sources/${source.id}/annotations/${existing.id}/crop`, c.signal).then(async response => { if (!response.ok) throw new Error(); url = URL.createObjectURL(await response.blob()); const image = new Image(); image.src = url; await image.decode(); if (!c.signal.aborted && canvas.current) { canvas.current.width=image.width; canvas.current.height=image.height; canvas.current.getContext("2d")?.drawImage(image,0,0); } }).catch(() => { if (!c.signal.aborted) setMessage("Unable to load the saved crop."); }).finally(() => { if (url) URL.revokeObjectURL(url); }); return () => { c.abort(); if(url) URL.revokeObjectURL(url); }; }, [existing, source.id]);
  async function save(event: FormEvent<HTMLFormElement>) { event.preventDefault(); if (!box) return; setBusy(true); setMessage(""); const values=new FormData(event.currentTarget); const payload: Record<string,unknown> = {};
    for (const field of ["question","response","first_error","observed_behaviours","observation_status","intervention","rationale"]) payload[field]=String(values.get(field) ?? "");
    for (const field of ["marks_awarded","marks_possible"]) payload[field] = values.get(field) ? Number(values.get(field)) : null;
    if (existing) payload.expected_revision=existing.revision; else { payload.client_annotation_id=key.current; payload.page_number=page.page_number; payload.bbox=box; }
    try { const response=await api(`sources/${source.id}/annotations${existing ? "/"+existing.id : ""}`,signal,{ method:existing?"PATCH":"POST", headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)}); if(!response.ok) { setMessage(response.status===409?"This annotation changed. Reload annotations, then reopen its row. Your current edits remain here until you do.":response.status===422?"Check the marks, source box, observation status, and intervention rationale.":"Save interrupted. Retry unchanged details."); return; } await onSaved(await response.json()); setMessage("Annotation saved."); } catch { if(!signal.aborted) setMessage("Save interrupted. Retry unchanged details."); } finally { setBusy(false); }
  }
  return <div className="mt-6 rounded-lg border bg-white p-4"><h5 className="font-semibold">{existing?`Edit annotation · revision ${existing.revision}`:"New annotation"}</h5><p className="mt-2 text-sm">{box?`Page ${page.page_number} · source box ${box.x.toFixed(1)}, ${box.y.toFixed(1)}, ${box.width.toFixed(1)} × ${box.height.toFixed(1)}`:"Select an area on the page first."}</p>
    {existing && <div className="mt-3"><p className="text-sm font-medium">Saved source crop</p><canvas ref={canvas} className="mt-2 max-w-full border" aria-label="Saved annotation source crop" /></div>}
    <form onSubmit={save} className="mt-4 grid gap-3 sm:grid-cols-2">{["question","response","first_error","observed_behaviours","intervention","rationale"].map(field=><label className="grid gap-1 text-sm capitalize sm:col-span-2" key={field}>{field.replaceAll("_"," ")}<textarea name={field} maxLength={8000} required={field==="question"} defaultValue={existing?.[field as keyof Annotation] as string ?? ""} disabled={busy} rows={2} className="rounded border p-2" /></label>)}
      {["marks_awarded","marks_possible"].map(field=><label className="grid gap-1 text-sm capitalize" key={field}>{field.replaceAll("_"," ")}<input name={field} type="number" min="0" max="1000" step="any" defaultValue={existing?.[field as keyof Annotation] as number ?? ""} disabled={busy} className="rounded border p-2" /></label>)}
      <label className="grid gap-1 text-sm">Observation status<select name="observation_status" defaultValue={existing?.observation_status??"not_observed"} disabled={busy} className="rounded border p-2"><option value="not_observed">Not observed</option><option value="observed">Observed in this crop</option><option value="inferred">Inferred — tentative</option></select></label>
      <button disabled={!box||busy} className="rounded bg-emerald-900 px-4 py-3 text-white disabled:opacity-40">{busy?"Saving…":existing?"Save changes":"Save annotation"}</button>
    </form>{message&&<p role="status" className="mt-3">{message}</p>}
  </div>;
}
