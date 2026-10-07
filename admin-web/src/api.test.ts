import {describe, expect, it, vi, afterEach} from 'vitest';
import {api, APIError, display} from './api';
afterEach(()=>vi.restoreAllMocks());
describe('server authoritative admin client',()=>{
 it('uses same-origin cookies and CSRF for writes',async()=>{
   const mock=vi.spyOn(globalThis,'fetch').mockResolvedValue(new Response(JSON.stringify({status:'ok'}),{status:200}));
   await api('control/flag/multi_agent',{enabled:false},'csrf-token');
   expect(mock.mock.calls[0][0]).toBe('/admin/control/flag/multi_agent');
   expect(mock.mock.calls[0][1]?.credentials).toBe('same-origin');
   expect((mock.mock.calls[0][1]?.headers as Record<string,string>)['X-CSRF-Token']).toBe('csrf-token');
 });
 it('surfaces authorization failures',async()=>{
   vi.spyOn(globalThis,'fetch').mockResolvedValue(new Response('',{status:403}));
   await expect(api('data/audit')).rejects.toBeInstanceOf(APIError);
 });
 it('renders null and structured values consistently',()=>{
   expect(display(null)).toBe('—');expect(display({x:1})).toBe('{"x":1}');
 });
});
