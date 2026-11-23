// Colour palettes per filament, and keeping settings valid when the filament
// or printer changes. The backend does the same mapping (palettes.py), so a
// colour moved here is the colour the project is written with.
import type { Color, Options, Settings } from './types';

export function paletteFor(options: Options, filament: string): Color[] {
	const line = options.filaments[filament]?.palette;
	return (line && options.palettes[line]) || options.colors;
}

export function paletteName(options: Options, filament: string): string {
	return options.filaments[filament]?.palette ?? 'PLA Matte';
}

function lab(hex: string): [number, number, number] {
	const h = hex.replace('#', '');
	const lin = [0, 2, 4].map((i) => {
		const c = parseInt(h.slice(i, i + 2), 16) / 255;
		return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
	});
	const x = (0.4124 * lin[0] + 0.3576 * lin[1] + 0.1805 * lin[2]) / 0.95047;
	const y = 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2];
	const z = (0.0193 * lin[0] + 0.1192 * lin[1] + 0.9505 * lin[2]) / 1.08883;
	const f = (t: number) => (t > 0.008856 ? Math.cbrt(t) : 7.787 * t + 16 / 116);
	return [116 * f(y) - 16, 500 * (f(x) - f(y)), 200 * (f(y) - f(z))];
}

export function nearest(palette: Color[], hex: string): Color | undefined {
	const a = lab(hex);
	let best: Color | undefined;
	let bestD = Infinity;
	for (const c of palette) {
		const b = lab(c.hex);
		const d = (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2;
		if (d < bestD) {
			bestD = d;
			best = c;
		}
	}
	return best;
}

/** The colour id the colour filter uses for a part with no colour. */
export const ANY_COLOR = 'any';

/** A colour id from any palette the server knows, `prefer` first. */
export function findColor(options: Options, id: string, prefer: Color[]): Color | undefined {
	return (
		prefer.find((c) => c.id === id) ??
		options.colors.find((c) => c.id === id) ??
		Object.values(options.palettes)
			.flat()
			.find((c) => c.id === id)
	);
}

function hexOf(options: Options, id: string, prefer: Color[]): string | undefined {
	return findColor(options, id, prefer)?.hex;
}

/** The colour filter carried to a new palette. Colours that were apart can
 *  land on one colour; that colour stays off only when every colour in use
 *  that moved onto it was off, so "only black" stays "only black". */
function moveFilter(excluded: string[], used: string[], options: Options, from: Color[], to: Color[]): string[] {
	const target = (id: string) => {
		if (id === ANY_COLOR) return id;
		const hex = hexOf(options, id, from);
		return hex ? nearest(to, hex)?.id : undefined;
	};
	const off = new Set(excluded);
	const stayOff = new Set<string>();
	const turnOn = new Set<string>();
	for (const id of used) {
		const t = target(id);
		if (t) (off.has(id) ? stayOff : turnOn).add(t);
	}
	return [...stayOff].filter((t) => !turnOn.has(t)).sort();
}

/** Settings made consistent with the options after a change: the filament
 *  exists for the printer, the plate type suits the filament, and every colour
 *  choice is a colour of the filament's palette (moved to the nearest one).
 *  `used` are the colours the parts list had before the change. */
export function adjust(next: Settings, options: Options, prev?: Settings, used?: string[]): Settings {
	const printer = options.printers.find((p) => p.id === next.printer) ?? options.printers[0];
	const filament = printer.filaments.includes(next.filament) ? next.filament : printer.filaments[0];
	const beds = printer.bed_types[filament] ?? options.bed_types;
	const bed_type = beds.includes(next.bed_type) ? next.bed_type : beds.includes('Textured PEI Plate') ? 'Textured PEI Plate' : beds[0];

	const palette = paletteFor(options, filament);
	const before = prev ? paletteFor(options, prev.filament) : palette;
	const role_colors: Record<string, string> = {};
	for (const role of options.color_roles) {
		const id = next.role_colors[role.id] ?? role.default;
		if (palette.some((c) => c.id === id)) {
			role_colors[role.id] = id;
			continue;
		}
		const hex = hexOf(options, id, before) ?? hexOf(options, role.default, before);
		role_colors[role.id] = (hex && nearest(palette, hex)?.id) || palette[0]?.id || id;
	}

	const excluded = Array.isArray(next.excluded_colors) ? next.excluded_colors : [];
	const excluded_colors =
		before === palette
			? excluded.filter((id) => id === ANY_COLOR || palette.some((c) => c.id === id))
			: moveFilter(excluded, used ?? excluded, options, before, palette);
	return { ...next, printer: printer.id, filament, bed_type, role_colors, excluded_colors };
}
