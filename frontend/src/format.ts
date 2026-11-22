export function grams(g: number): string {
	return g >= 1000 ? `${(g / 1000).toFixed(2)} kg` : `${Math.round(g)} g`;
}

export function hours(sec: number): string {
	if (sec < 3600) return `${Math.round(sec / 60)} min`;
	const h = sec / 3600;
	return h >= 100 ? `${Math.round(h)} h` : `${h.toFixed(1)} h`;
}

export function megabytes(bytes: number): string {
	return `${(bytes / 1e6).toFixed(1)} MB`;
}
