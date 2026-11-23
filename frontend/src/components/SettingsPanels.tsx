import { paletteFor, paletteName } from '../palette';
import type { LayerSize, Options, Settings } from '../types';
import { ColorPicker, NumberField, Panel, Row, Segmented, Toggle } from './controls';

type Props = { settings: Settings; options: Options; update: (patch: Partial<Settings>) => void };

export function MachinePanel({ settings, options, update }: Props) {
	const layers = settings.layers;
	const setLayer = (i: number, size: LayerSize) => update({ layers: layers.map((s, j) => (j === i ? size : s)) });
	return (
		<Panel title="Machine">
			<Row label="Layers" hint="Each layer has its own distribution frame, chute and funnel. Pick 12 or 18 bins per layer, or remove them all to print only the rest.">
				<div className="layers">
					{layers.length === 0 ? <span className="muted">No layers</span> : null}
					{layers.map((size, i) => (
						<div className="layer" key={i}>
							<span className="layer-name">Layer {i + 1}</span>
							<Segmented<LayerSize>
								label={`Layer ${i + 1} bins`}
								value={size}
								onChange={(v) => setLayer(i, v)}
								options={[
									{ value: 'half', label: '12 bins' },
									{ value: 'third', label: '18 bins' }
								]}
							/>
							<button
								type="button"
								className="icon-button"
								aria-label={`Remove layer ${i + 1}`}
								onClick={() => update({ layers: layers.filter((_, j) => j !== i) })}
							>
								×
							</button>
						</div>
					))}
					<button type="button" className="button" disabled={layers.length >= 16} onClick={() => update({ layers: [...layers, 'third'] })}>
						Add layer
					</button>
				</div>
			</Row>
			{options.alternatives.map((alt) => (
				<Row key={alt.id} label={alt.label}>
					<select
						value={settings.alternatives[alt.id] ?? alt.options[0].id}
						onChange={(e) => update({ alternatives: { ...settings.alternatives, [alt.id]: e.target.value } })}
					>
						{alt.options.map((o) => (
							<option key={o.id} value={o.id}>
								{o.label}
							</option>
						))}
					</select>
				</Row>
			))}
			<Row label="Optional parts" hint="Parts the machine works without.">
				<Toggle checked={settings.include_optional} onChange={(v) => update({ include_optional: v })} label="Include optional parts" />
			</Row>
			<Row label="Version ids" hint="Recess each part's version id into a face, as the parts calculator's downloads do.">
				<Toggle checked={settings.engrave_ids} onChange={(v) => update({ engrave_ids: v })} label="Engrave version ids" />
			</Row>
		</Panel>
	);
}

export function ColorsPanel({ settings, options, update }: Props) {
	const palette = paletteFor(options, settings.filament);
	const line = paletteName(options, settings.filament);
	return (
		<Panel
			title="Colours"
			actions={
				<button type="button" className="link-button" onClick={() => update({ role_colors: { ...options.defaults.role_colors } })}>
					Reset
				</button>
			}
		>
			<p className="panel-note">
				Each group sets the colour of every part in it. Parts whose colour does a job, like the gray rotors and stators the cameras look at, keep
				their colour. Colours are Bambu Lab {line}; switching filament moves each choice to the nearest colour it comes in.
			</p>
			<div className="color-grid">
				{options.color_roles.map((r) => (
					<div className="color-role" key={r.id}>
						<span className="color-role-name">{r.name}</span>
						<ColorPicker
							label={r.name}
							colors={palette}
							value={settings.role_colors[r.id] ?? r.default}
							onChange={(id) => update({ role_colors: { ...settings.role_colors, [r.id]: id } })}
						/>
					</div>
				))}
			</div>
		</Panel>
	);
}

export function PrintPanel({ settings, options, update }: Props) {
	const printer = options.printers.find((p) => p.id === settings.printer) ?? options.printers[0];
	const beds = printer?.bed_types[settings.filament] ?? options.bed_types;
	return (
		<Panel
			title="Printer and print settings"
			actions={
				<button type="button" className="link-button" onClick={() => update({ ...options.recommended })} title="3 walls, gyroid infill, outer wall 80 mm/s at 2500 mm/s²">
					Recommended
				</button>
			}
		>
			<p className="panel-note">
				Bambu's {printer?.process ?? '0.20mm Standard'} preset, with gyroid infill. Empty fields keep the preset's value. If walls come out
				rough, "Recommended" sets what the Sorter community prints with: 3 walls and a slower outer wall (80 mm/s, 2500 mm/s²).
			</p>
			<Row
				label="Printer"
				hint={
					printer ? (
						<>
							{printer.bed.width} × {printer.bed.depth} mm bed · {printer.process}
							{printer.note ? <div>{printer.note}</div> : null}
						</>
					) : undefined
				}
			>
				<select value={settings.printer} onChange={(e) => update({ printer: e.target.value })}>
					{options.printers.map((p) => (
						<option key={p.id} value={p.id}>
							{p.name}
						</option>
					))}
				</select>
			</Row>
			<Row
				label="Filament"
				hint={
					<>
						Dry it first if the roll has been open a while; a new roll is usually fine.
						{settings.filament.includes('PETG') ? ' PETG prints on the textured or smooth PEI plates, not the Cool Plate.' : null}
					</>
				}
			>
				<select value={settings.filament} onChange={(e) => update({ filament: e.target.value })}>
					{(printer?.filaments ?? []).map((f) => (
						<option key={f} value={f}>
							{f}
						</option>
					))}
				</select>
			</Row>
			<Row label="Plate type" hint="Only the plates this filament's profile prints on.">
				<select value={settings.bed_type} onChange={(e) => update({ bed_type: e.target.value })}>
					{beds.map((b) => (
						<option key={b} value={b}>
							{b}
						</option>
					))}
				</select>
			</Row>
			<Row label="Layer height">
				<NumberField value={settings.layer_height} min={0.08} max={0.32} step={0.04} suffix="mm" onChange={(v) => update({ layer_height: v ?? 0.2 })} />
			</Row>
			<Row label="Infill" hint="The catalog's gram figures were sliced at 15% adaptive cubic.">
				<div className="inline">
					<NumberField value={settings.infill_density} min={0} max={100} suffix="%" onChange={(v) => update({ infill_density: v ?? 15 })} />
					<select value={settings.infill_pattern} onChange={(e) => update({ infill_pattern: e.target.value })} aria-label="Infill pattern">
						{options.infill_patterns.map((p) => (
							<option key={p} value={p}>
								{p}
							</option>
						))}
					</select>
				</div>
			</Row>
			<Row label="Walls" hint="Leave empty to keep the preset's (2).">
				<NumberField value={settings.wall_loops} min={1} max={10} placeholder="preset" onChange={(v) => update({ wall_loops: v })} />
			</Row>
			<Row label="Outer wall" hint="Speed and acceleration. Slower gives cleaner walls. Leave empty for the preset's (200 mm/s, 5000 mm/s² or more).">
				<div className="inline">
					<NumberField value={settings.outer_wall_speed} min={10} max={1000} placeholder="preset" suffix="mm/s" onChange={(v) => update({ outer_wall_speed: v })} />
					<NumberField
						value={settings.outer_wall_acceleration}
						min={200}
						max={30000}
						step={100}
						placeholder="preset"
						suffix="mm/s²"
						onChange={(v) => update({ outer_wall_acceleration: v === null ? null : Math.round(v) })}
					/>
				</div>
			</Row>
			<Row label="Brim">
				<Segmented
					label="Brim"
					value={settings.brim}
					onChange={(v) => update({ brim: v })}
					options={[
						{ value: 'auto', label: 'Auto' },
						{ value: 'outer', label: 'Outer' },
						{ value: 'none', label: 'None' }
					]}
				/>
			</Row>
			<Row label="Supports" hint="Only for the parts the catalog prints with support (the stator, chute core, funnels and a few more). Tree supports spread wide, so those parts get more room.">
				<Segmented
					label="Supports"
					value={settings.supports}
					onChange={(v) => update({ supports: v })}
					options={[
						{ value: 'catalog', label: 'Normal' },
						{ value: 'tree', label: 'Tree' },
						{ value: 'off', label: 'Off' }
					]}
				/>
			</Row>
			<Row
				label="Part poses"
				hint="A few parts are exported the way they sit in the machine: on an edge (the bins), upside down with a roof in mid-air (the lamp covers), or a thin plate standing on its end (the arm brackets). These are turned onto the flat face that needs the least support; the build report lists them."
			>
				<Toggle checked={settings.auto_orient} onChange={(v) => update({ auto_orient: v })} label="Turn parts that would print badly as exported" />
			</Row>
			<Row label="Plates" hint="One colour per plate either way, so no filament changes are needed.">
				<Segmented
					label="Group plates by"
					value={settings.group_by}
					onChange={(v) => update({ group_by: v })}
					options={[
						{ value: 'color', label: 'By colour' },
						{ value: 'section', label: 'By section' }
					]}
				/>
			</Row>
			<Row label="Spacing" hint="Between parts, and from the plate's edge.">
				<div className="inline">
					<NumberField value={settings.spacing_mm} min={1} max={30} suffix="mm apart" onChange={(v) => update({ spacing_mm: v ?? 4 })} />
					<NumberField value={settings.edge_mm} min={0} max={20} suffix="mm edge" onChange={(v) => update({ edge_mm: v ?? 2 })} />
				</div>
			</Row>
		</Panel>
	);
}
