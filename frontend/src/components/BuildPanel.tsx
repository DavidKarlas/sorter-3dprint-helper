import { grams, hours, megabytes } from '../format';
import type { Bom, Job, Options } from '../types';
import { Panel, Swatch } from './controls';
import { PlateView } from './PlateView';

type Props = {
	bom: Bom | null;
	options: Options;
	job: Job | null;
	busy: boolean;
	stale: boolean;
	error: string | null;
	onBuild: () => void;
	/** print settings use more plastic than the catalog's slices (2 walls, 15% adaptive cubic) */
	heavier: boolean;
};

export function BuildPanel({ bom, job, busy, stale, error, onBuild, heavier }: Props) {
	const t = bom?.totals;
	const result = job?.status === 'done' ? job.result : undefined;
	return (
		<Panel title="Build">
			<div className="totals">
				<Stat
					label="Parts"
					value={t ? `${t.pieces}` : '–'}
					sub={t ? `${t.part_types} kinds${t.printed ? ` · ${t.printed} printed already` : ''}` : undefined}
				/>
				<Stat
					label="Filament"
					value={t ? grams(t.grams) : '–'}
					sub={
						heavier
							? 'catalog slices (2 walls, 15% adaptive cubic); your settings use more'
							: bom && Math.abs(bom.grams_factor - 1) > 0.001
								? 'PLA Matte slices, scaled by density'
								: 'slicer-measured, per part'
					}
				/>
				<Stat label="Print time" value={t ? hours(t.seconds) : '–'} sub="each part alone, summed" />
			</div>
			<div className="build-row">
				<button type="button" className="button primary" onClick={onBuild} disabled={busy || !t || t.pieces === 0}>
					{busy ? 'Building…' : result ? 'Build again' : 'Build 3MF'}
				</button>
				<p className="hint">
					Downloads every part from the catalog, lays them out on plates one colour at a time, and writes Bambu Studio projects with your
					printer, filament and settings already chosen.
				</p>
			</div>
			{error ? <div className="callout danger">{error}</div> : null}
			{job && (job.status === 'queued' || job.status === 'running') ? (
				<div className="progress" role="status">
					<div className="progress-bar">
						<div style={{ width: `${Math.round(job.progress * 100)}%` }} />
					</div>
					<span className="muted">{job.message}</span>
				</div>
			) : null}
			{job?.status === 'failed' ? <div className="callout danger">The build failed: {job.error}</div> : null}
			{result ? (
				<>
					{stale ? <div className="callout warn">Settings changed since this build. Build again to apply them.</div> : null}
					<div className="files">
						{result.files.map((f) => {
							const abs = new URL(f.url, window.location.href).href;
							return (
								<div className="file" key={f.name}>
									<div>
										<div className="file-name">{f.name}</div>
										<div className="muted small">
											{f.plates.length} plates · {megabytes(f.size)} ·{' '}
											{f.colours.map((c) => (
												<Swatch key={c} hex={c} size={10} />
											))}
										</div>
									</div>
									<div className="file-actions">
										<a className="button" href={`bambustudio://open?file=${encodeURIComponent(abs)}`} title="Needs Bambu Studio installed, and this server reachable from it">
											Open in Bambu Studio
										</a>
										<a className="button primary" href={f.url} download>
											Download
										</a>
									</div>
								</div>
							);
						})}
						{result.zip_url ? (
							<p className="muted small">
								Bambu Studio holds at most 36 plates per project, so this build is split into {result.files.length} files.{' '}
								<a href={result.zip_url}>Download all as one zip</a>.
							</p>
						) : null}
					</div>
					{result.warnings.length ? (
						<details className="warnings">
							<summary>{result.warnings.length} notes about this build</summary>
							<ul>
								{result.warnings.map((w, i) => (
									<li key={i}>{w}</li>
								))}
							</ul>
						</details>
					) : null}
				</>
			) : null}
		</Panel>
	);
}

export function PlatesPanel({ job }: { job: Job | null }) {
	const result = job?.status === 'done' ? job.result : undefined;
	if (!result) return null;
	const byFile = result.files.map((f) => ({ file: f, plates: f.plates.map((i) => result.plates[i]) }));
	return (
		<Panel title={`Plates (${result.plates.length})`}>
			{byFile.map(({ file, plates }) => (
				<div key={file.name} className="plate-file">
					{result.files.length > 1 ? <h3>{file.name}</h3> : null}
					<div className="plates">
						{plates.map((p, i) => (
							<figure key={p.index} className={`plate${p.oversize ? ' oversize' : ''}`}>
								<PlateView plate={p} result={result} />
								<figcaption>
									<div className="plate-title">
										<span className="faint">{i + 1}</span> {p.name}
									</div>
									<div className="muted small">
										{p.pieces.length} parts · {grams(p.grams)} · ~{hours(p.seconds)}
									</div>
								</figcaption>
							</figure>
						))}
					</div>
				</div>
			))}
			<p className="muted small">
				Outlines are each part's footprint as placed. Grams and hours add up the catalog's per-part slices, so a full plate prints somewhat faster
				than shown.
			</p>
		</Panel>
	);
}

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
	return (
		<div className="stat">
			<div className="stat-label">{label}</div>
			<div className="stat-value">{value}</div>
			{sub ? <div className="faint small">{sub}</div> : null}
		</div>
	);
}
