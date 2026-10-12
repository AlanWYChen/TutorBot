"use client";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { tutorAuth } from "../lib/firebase";
import type { Box } from "../lib/page-coordinates";

export type Annotation = { id: string; document_id: string; page_number: number; bbox: Box; revision: number; question: string; response: string; marks_awarded: number | null; marks_possible: number | null; first_error: string; observed_behaviours: string; observation_status: string; intervention: string; rationale: string };
export const studioButton = "rounded-lg border border-emerald-900/20 px-3 py-2 text-sm disabled:opacity-40";
export function sourceName(filename: string) {
  if(filename === "synthetic-holdout-v1.pdf") return "Practice questions — held out";
  if(filename === "synthetic-development-v1.pdf") return "Practice questions — development";
  return filename.replace(/\.pdf$/i, "").replaceAll("_", " ");
}
export async function studioApi(path: string, init: RequestInit = {}, signal?: AbortSignal) {
  const user=(await tutorAuth()).currentUser;if(!user)throw new Error("Sign in to continue.");
  const headers=new Headers(init.headers);headers.set("Authorization",`Bearer ${await user.getIdToken()}`);
  if(typeof init.body==="string")headers.set("Content-Type","application/json");
  const response=await fetch(`/api/studio/${path}`,{...init,headers,signal,cache:"no-store"});
  if(!response.ok){const data=await response.json().catch(()=>null);throw new Error(data?.detail??"Unable to complete this request.");}
  return response;
}
export function SourceCrop({path}:{path:string}) {
  const [url,setUrl]=useState("");const [error,setError]=useState(false);
  useEffect(()=>{const c=new AbortController();let blobUrl="";studioApi(path,{},c.signal).then(r=>r.blob()).then(blob=>{if(!c.signal.aborted){blobUrl=URL.createObjectURL(blob);setUrl(blobUrl);}}).catch(()=>{if(!c.signal.aborted)setError(true);});return()=>{c.abort();if(blobUrl)URL.revokeObjectURL(blobUrl);};},[path]);
  // Private crops are fetched with authentication and revoked when the editor closes.
  // eslint-disable-next-line @next/next/no-img-element
  return error?<p role="alert">Unable to load the source crop.</p>:url?<img src={url} alt="Annotation source crop" className="max-h-80 max-w-full rounded border object-contain" />:<p>Loading source crop…</p>;
}
export function AnnotationEditor({documentId,pageNumber,box,existing,onSaved,onDeleted,onDirty}:{documentId:string;pageNumber:number;box:Box|null;existing:Annotation|null;onSaved:(note:Annotation)=>Promise<void>;onDeleted?:()=>Promise<void>;onDirty?:(dirty:boolean)=>void}) {
  const [busy,setBusy]=useState(false);const [message,setMessage]=useState("");const key=useRef(crypto.randomUUID());const formRef=useRef<HTMLFormElement>(null);const [changed,setChanged]=useState(false);
  const fields=[['question','Question'],['response','Response'],['first_error','First error'],['observed_behaviours','Comments / visible behaviour']];
  async function save(event:FormEvent<HTMLFormElement>){event.preventDefault();if(!box)return;const values=new FormData(event.currentTarget);setBusy(true);setMessage("");const payload:Record<string,unknown>={};
    for(const field of ["question","response","first_error","observed_behaviours","observation_status","intervention","rationale"])payload[field]=String(values.get(field)??"");
    for(const field of ["marks_awarded","marks_possible"])payload[field]=values.get(field)?Number(values.get(field)):null;
    if(!payload.observed_behaviours)payload.observation_status="not_observed";
    if(existing)payload.expected_revision=existing.revision;else{payload.client_annotation_id=key.current;payload.page_number=pageNumber;payload.bbox=box;}
    try{const response=await studioApi(`sources/${documentId}/annotations${existing?"/"+existing.id:""}`,{method:existing?"PATCH":"POST",body:JSON.stringify(payload)});await onSaved(await response.json());onDirty?.(false);setMessage("Saved. Review now shows these labels.");}
    catch(error){setMessage(error instanceof Error?error.message:"Unable to save.");}finally{setBusy(false);}
  }
  async function remove(){setBusy(true);setMessage("");try{await studioApi(`sources/${documentId}/annotations/${existing!.id}`,{method:"DELETE"});await onDeleted?.();}catch(error){setMessage(error instanceof Error?error.message:"Unable to delete.");}finally{setBusy(false);}}
  return <section aria-label="Annotation labels" className="rounded-xl border bg-white p-4">
    <div className="mb-4 flex flex-wrap items-center justify-between gap-2"><h4 className="font-semibold">{existing?"Edit labels":"New annotation"}</h4>{existing&&onDeleted&&<button className={`${studioButton} text-red-800`} disabled={busy} onClick={remove}>Delete annotation</button>}</div>
    {existing&&<div className="mb-4"><p className="mb-2 text-xs font-medium text-slate-500">Source · page {pageNumber}</p><SourceCrop key={existing.id} path={`sources/${documentId}/annotations/${existing.id}/crop`} /></div>}
    {!box&&<p className="mb-3 text-sm text-slate-600">Select the question area on the PDF to start.</p>}
    <form ref={formRef} onSubmit={save} onChange={()=>{setChanged(true);onDirty?.(true);}} className="grid gap-4">
      {fields.map(([field,label])=><label key={field} className="grid gap-1 text-sm">{label}<textarea name={field} required={field==="question"} maxLength={8000} rows={2} defaultValue={existing?.[field as keyof Annotation] as string??""} disabled={busy} className="w-full rounded-lg border p-2" /></label>)}
      <div className="grid grid-cols-2 gap-3">{[["marks_awarded","Marks awarded"],["marks_possible","Out of"]].map(([field,label])=><label key={field} className="grid gap-1 text-sm">{label}<input name={field} type="number" min={0} max={1000} step="any" defaultValue={existing?.[field as keyof Annotation] as number??""} disabled={busy} className="min-w-0 rounded-lg border p-2" /></label>)}</div>
      <details className="rounded-lg bg-slate-50 p-3"><summary className="cursor-pointer text-sm font-medium">Teaching feedback and observation details</summary><div className="mt-3 grid gap-3"><label className="grid gap-1 text-sm">Observation<select name="observation_status" defaultValue={existing?.observation_status==="inferred"?"inferred":"observed"} className="rounded border p-2"><option value="observed">Visible in this work</option><option value="inferred">Tentative interpretation</option></select></label>{[["intervention","Teaching suggestion"],["rationale","Why this helps"]].map(([field,label])=><label className="grid gap-1 text-sm" key={field}>{label}<textarea name={field} maxLength={8000} rows={2} defaultValue={existing?.[field as keyof Annotation] as string??""} disabled={busy} className="rounded border p-2" /></label>)}</div></details>
      <button disabled={!box||busy} className="rounded-lg bg-emerald-900 px-4 py-3 text-white disabled:opacity-40">{busy?"Saving…":existing?"Save changes":"Save annotation"}</button>
      {changed&&<button type="button" className={studioButton} disabled={busy} onClick={()=>{formRef.current?.reset();setChanged(false);onDirty?.(false);setMessage("");}}>Discard unsaved changes</button>}
    </form>{message&&<p role="status" className="mt-3 text-sm">{message}</p>}
  </section>;
}
