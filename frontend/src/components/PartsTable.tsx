import { useMemo, useState } from 'react';
import { grams } from '../format';
import type { Bom, BomLine, Options, Settings } from '../types';
import { ANY_COLOR, paletteFor } from '../palette';
import { NumberField, Panel, Swatch } from './controls';

type Props = {
	bom: Bom | null;
	options: Options;
	settings: Settings;
	update: (patch: Partial<Settings>) => void;
};

/** Pieces a line needs, per colour. */
function needByColor(l: BomLine): Record<string, number> {
	const out: Record<string, number> = {};
	for (const u of l.units) {
		const id = u.color_id ?? ANY_COLOR;
		out[id] = (out[id] ?? 0) + u.count;
	}
	return out;
}

export function PartsTable({ bom, options, settings, update }: Props) {
	const [filter, setFilter] = useState('');
	const [showAll, setShowAll] = useState(false);
	const [hideDone, setHideDone] = useState(false);
	const palette = paletteFor(options, settings.filament);
	const colors = useMemo(() => new Map(palette.map((c) => [c.id, c])), [palette]);
	const sections = useMemo(() => new Map(options.sections.map((s) => [s.id, s.name])), [options.sections]);
	const edited = Object.keys(settings.qty_overrides).length;

	const setQty = (line: BomLine, n: number | null) => {
		const next = { ...settings.qty_overrides };
		if (n === null || n === line.needed) delete next[line.id];
		else next[line.id] = n;
		update({ qty_overrides: next });
	};

	const setPrinted = (line: BomLine, colorId: string, n: number | null) => {
		const next = { ...settings.printed };
		const per = { ...(next[line.id] ?? {}) };
		if (!n) delete per[colorId];
		else per[colorId] = n;
		if (Object.keys(per).length) next[line.id] = per;
		else delete next[line.id];
		update({ printed: next });
	};
	// the ✓: every piece this line needs is printed, or none is
	const toggleDone = (line: BomLine, done: boolean) => {
		const next = { ...settings.printed };
		if (done) delete next[line.id];
		else next[line.id] = needByColor(line);
		update({ printed: next });
	};
	const printedParts = Object.keys(settings.printed).length;
	const isDone = (l: BomLine) => l.qty > 0 && l.to_print === 0;

	// a part nothing selected needs, and nobody asked for by hand, is hidden unless asked
	const relevant = (l: BomLine) => l.qty > 0 || l.needed > 0 || settings.qty_overrides[l.id] !== undefined;
	const hidden = (bom?.lines ?? []).filter((l) => !relevant(l)).length;
	const doneCount = (bom?.lines ?? []).filter(isDone).length;
	const lines = (bom?.lines ?? []).filter((l) => {
		if (!showAll && !relevant(l)) return false;
		if (hideDone && isDone(l)) return false;
		const q = filter.trim().toLowerCase();
		return !q || l.name.toLowerCase().includes(q) || l.id.includes(q) || (l.uid ?? '').toLowerCase().includes(q);
	});

	return (
		<Panel
			title="Parts"
			actions={
				<>
					{hidden ? (
						<label className="toggle small">
							<input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} />
							<span>Show {hidden} not selected</span>
						</label>
					) : null}
					{doneCount ? (
						<label className="toggle small">
							<input type="checkbox" checked={hideDone} onChange={(e) => setHideDone(e.target.checked)} />
							<span>Hide {doneCount} printed</span>
						</label>
					) : null}
					{edited ? (
						<button type="button" className="link-button" onClick={() => update({ qty_overrides: {} })}>
							Reset {edited} edited
						</button>
					) : null}
					{printedParts ? (
						<button
							type="button"
							className="link-button"
							onClick={() => {
								if (window.confirm(`Forget what is printed of ${printedParts} parts?`)) update({ printed: {} });
							}}
						>
							Clear printed
						</button>
					) : null}
					<input className="search" type="search" placeholder="Filter parts" value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Filter parts" />
				</>
			}
		>
			{!bom ? (
				<p className="panel-note">Loading the parts list…</p>
			) : (
				<div className="table-wrap">
					<table className="parts">
						<thead>
							<tr>
								<th className="check" aria-label="Print" />
								<th>Part</th>
								<th>Section</th>
								<th>Colour</th>
								<th className="num">Qty</th>
								<th className="num" title="Pieces already printed: a build prints only the rest">
									Printed
								</th>
								<th className="num">Each</th>
								<th>Notes</th>
							</tr>
						</thead>
						<tbody>
							{lines.map((l) => {
								const off = l.qty === 0;
								const done = isDone(l);
								const isEdited = settings.qty_overrides[l.id] !== undefined;
								const need = needByColor(l);
								const mine = settings.printed[l.id] ?? {};
								// the line's colours, and any it was printed in that it no longer uses
								const printColors = [...new Set([...Object.keys(need), ...Object.keys(mine)])];
								const byColor = new Map<string, number>();
								for (const u of l.units) byColor.set(u.color_id ?? 'any', (byColor.get(u.color_id ?? 'any') ?? 0) + u.count);
								return (
									<tr key={l.id} className={off ? 'off' : done ? 'done' : ''}>
										<td className="check">
											<input
												type="checkbox"
												checked={!off}
												aria-label={`Print ${l.name}`}
												onChange={(e) => setQty(l, e.target.checked ? (l.needed > 0 ? null : 1) : 0)}
											/>
										</td>
										<td>
											<div className="part-name">{l.name}</div>
											{l.uid ? <div className="mono faint">{l.uid}</div> : null}
										</td>
										<td className="muted">{l.sections.map((s) => sections.get(s) ?? s).join(', ')}</td>
										<td>
											<div className="swatches">
												{[...byColor.entries()].map(([cid, n]) => {
													const c = colors.get(cid);
													return (
														<span key={cid} className="swatch-count" title={c?.name ?? 'Any colour'}>
															<Swatch hex={c?.hex ?? '#999999'} />
															{byColor.size > 1 ? <span className="faint">{n}</span> : null}
														</span>
													);
												})}
											</div>
										</td>
										<td className="num">
											<NumberField value={l.qty} min={0} max={1000} onChange={(n) => setQty(l, n)} />
											{isEdited ? <div className="faint small">needs {l.needed}</div> : null}
										</td>
										<td className="num printed">
											{printColors.length ? (
												<div className="printed-cell">
													<div className="printed-fields">
														{printColors.map((cid) => {
															const c = colors.get(cid);
															return (
																<span key={cid} className="printed-field" title={need[cid] === undefined ? `${c?.name ?? cid}: this part is no longer that colour` : c?.name}>
																	{printColors.length > 1 ? <Swatch hex={c?.hex ?? '#999999'} size={10} /> : null}
																	<NumberField value={mine[cid] ?? null} placeholder="0" min={0} max={10000} onChange={(n) => setPrinted(l, cid, n)} />
																</span>
															);
														})}
													</div>
													{l.qty > 0 ? (
														<button
															type="button"
															className="done-toggle"
															aria-pressed={done}
															aria-label={done ? `Mark ${l.name} not printed` : `Mark all ${l.name} printed`}
															title={done ? 'Printed. Click to clear.' : 'Mark all printed'}
															onClick={() => toggleDone(l, done)}
														>
															✓
														</button>
													) : null}
												</div>
											) : (
												<span className="faint">–</span>
											)}
											{l.printed > 0 && l.to_print > 0 ? <div className="faint small">{l.to_print} left</div> : null}
										</td>
										<td className="num muted">{l.grams != null ? grams(l.grams) : '–'}</td>
										<td>
											<div className="chips">
												{l.required_color ? (
													<span className="chip info" title={l.required_color.why}>
														must be {colors.get(l.required_color.color_id)?.name ?? l.required_color.color_id}
													</span>
												) : null}
												{l.support ? <span className="chip">support</span> : null}
												{l.optional && !l.in_bins ? <span className="chip">optional</span> : null}
												{l.low_tolerance ? <span className="chip warn" title="Tight fit: a test print is worth doing.">tight fit</span> : null}
												{l.orientation_note ? (
													<span className="chip warn" title={l.orientation_note}>
														orientation
													</span>
												) : null}
											</div>
										</td>
									</tr>
								);
							})}
						</tbody>
					</table>
				</div>
			)}
		</Panel>
	);
}
