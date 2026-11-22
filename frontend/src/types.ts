// Shapes of the backend API (backend/sorter3mf/api.py).

export type LayerSize = 'third' | 'half';

export type Settings = {
	layers: LayerSize[];
	/** assembly-tree places not to print (leaf keys from Bom.tree) */
	excluded: string[];
	include_optional: boolean;
	alternatives: Record<string, string>;
	role_colors: Record<string, string>;
	qty_overrides: Record<string, number>;
	engrave_ids: boolean;
	printer: string;
	filament: string;
	bed_type: string;
	layer_height: number;
	infill_density: number;
	infill_pattern: string;
	wall_loops: number | null;
	outer_wall_speed: number | null;
	outer_wall_acceleration: number | null;
	brim: 'auto' | 'none' | 'outer';
	supports: 'catalog' | 'tree' | 'off';
	spacing_mm: number;
	edge_mm: number;
	group_by: 'color' | 'section';
};

export type Color = { id: string; name: string; hex: string };
export type ColorRole = { id: string; name: string; default: string };
export type Section = { id: string; name: string; scales_with_layers: boolean };
export type Printer = {
	id: string;
	name: string;
	process: string;
	filaments: string[];
	/** plate types each filament can be printed on */
	bed_types: Record<string, string[]>;
	bed: { width: number; depth: number; height: number };
	bambu_studio_version: string;
};
export type Alternative = { id: string; label: string; options: { id: string; label: string }[] };

export type Options = {
	/** this app's source code (AGPL), when the server is told where it is */
	source_url: string | null;
	catalog: { source: string; fetched_at: number; printer: string; process: string; filament: string };
	sections: Section[];
	color_roles: ColorRole[];
	/** the catalog's own palette (PLA Matte) */
	colors: Color[];
	/** colours per filament line, e.g. "PETG Matte" */
	palettes: Record<string, Color[]>;
	filaments: Record<string, { palette: string }>;
	alternatives: Alternative[];
	printers: Printer[];
	bed_types: string[];
	infill_patterns: string[];
	brims: string[];
	/** the community-recommended print settings (also the defaults) */
	recommended: Pick<Settings, 'wall_loops' | 'infill_pattern' | 'outer_wall_speed' | 'outer_wall_acceleration'>;
	defaults: Settings;
};

export type BomUnit = { section: string; color_id: string | null; count: number };
export type BomLine = {
	id: string;
	name: string;
	uid: string | null;
	needed: number;
	qty: number;
	sections: string[];
	units: BomUnit[];
	grams: number | null;
	print_seconds: number | null;
	optional: boolean;
	in_bins: boolean;
	support: boolean;
	required_color: { color_id: string; why: string } | null;
	orientation_note: string | null;
	low_tolerance: boolean;
	render: string | null;
	stl_url: string;
};
export type TreeNode = {
	key: string;
	name: string;
	mult: number;
	total: number;
	selected: number;
	parts: string[];
	children: TreeNode[];
};
export type Bom = {
	/** the filament line the colours below belong to */
	palette: string;
	/** catalog grams are PLA Matte slices; this is the density ratio applied */
	grams_factor: number;
	tree: TreeNode;
	lines: BomLine[];
	totals: { part_types: number; pieces: number; grams: number; seconds: number };
};

export type PlacedPiece = { part_id: string; name: string; x: number; y: number; rotation: number; w: number; d: number };
export type PlateOut = {
	index: number;
	name: string;
	file: string | null;
	section: string | null;
	color: Color;
	oversize: boolean;
	grams: number;
	seconds: number;
	pieces: PlacedPiece[];
};
export type FileOut = { name: string; url: string; plates: number[]; colours: string[]; size: number };
export type BuildResult = {
	bed: { width: number; depth: number; exclude: number[][] };
	warnings: string[];
	footprints: Record<string, number[][]>;
	files: FileOut[];
	zip_url: string | null;
	plates: PlateOut[];
};
export type Job = {
	id: string;
	status: 'queued' | 'running' | 'done' | 'failed';
	stage: string;
	progress: number;
	message: string;
	error: string | null;
	result?: BuildResult;
};
