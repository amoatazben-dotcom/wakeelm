export type Row = Record<string, string | number | boolean | null | Record<string, unknown>>;
export type Page = {items: Row[]; total: number; page: number};
export type Identity = {subject:string; role:string; permissions:string[]; csrf:string|null};
export type Health = {readiness: unknown; queue_depth:number; pending_approvals:number; release:Record<string,string>};
export class APIError extends Error {constructor(public status:number){super(`HTTP ${status}`)}}
export async function api<T>(path:string, body?:unknown, csrf?:string|null):Promise<T> {
  const response = await fetch(`/admin/${path}`, {credentials:'same-origin', method:body ? 'POST':'GET',
    headers:body ? {'Content-Type':'application/json', 'X-CSRF-Token':csrf ?? ''}:{},
    body:body ? JSON.stringify(body):undefined, signal:AbortSignal.timeout(15000)});
  if (!response.ok) throw new APIError(response.status);
  return await response.json() as T;
}
export function display(value:Row[string]):string {
  return value === null ? '—' : typeof value === 'object' ? JSON.stringify(value):String(value);
}
