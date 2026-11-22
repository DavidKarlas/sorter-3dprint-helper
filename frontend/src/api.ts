import type { Bom, Job, Options, Settings } from './types';

async function request<T>(url: string, init?: RequestInit): Promise<T> {
	const res = await fetch(url, {
		...init,
		headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) }
	});
	if (!res.ok) {
		let detail = `${res.status} ${res.statusText}`;
		try {
			const body = await res.json();
			if (typeof body.detail === 'string') detail = body.detail;
			else if (Array.isArray(body.detail)) detail = body.detail.map((d: { msg: string }) => d.msg).join('; ');
		} catch {
			/* not JSON */
		}
		throw new Error(detail);
	}
	return res.json() as Promise<T>;
}

export const getOptions = () => request<Options>('/api/options');

export const getBom = (s: Settings, signal?: AbortSignal) =>
	request<Bom>('/api/bom', { method: 'POST', body: JSON.stringify(s), signal });

export const startJob = (s: Settings) =>
	request<{ id: string }>('/api/jobs', { method: 'POST', body: JSON.stringify(s) });

export const getJob = (id: string) => request<Job>(`/api/jobs/${id}`);
