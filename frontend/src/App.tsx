import { useCallback, useEffect, useRef, useState } from 'react';
import { getBom, getJob, getOptions, startJob } from './api';
import { BuildPanel, PlatesPanel } from './components/BuildPanel';
import { PartsTable } from './components/PartsTable';
import { SelectionTree } from './components/SelectionTree';
import { ColorsPanel, MachinePanel, PrintPanel } from './components/SettingsPanels';
import { adjust } from './palette';
import type { Bom, Job, Options, Settings } from './types';

const STORE_KEY = 'sorter3mf-settings-v4';
// Older saves carry print defaults that have since changed. Keep everything
// else (layers, colours, what to print) and let the current defaults apply
// to these: v3 saved 3 walls and an 80 mm/s outer wall, v2 adaptive cubic.
const OLDER: [string, (keyof Settings)[]][] = [
	['sorter3mf-settings-v3', ['wall_loops', 'outer_wall_speed', 'outer_wall_acceleration']],
	['sorter3mf-settings-v2', ['wall_loops', 'outer_wall_speed', 'outer_wall_acceleration', 'infill_pattern']]
];

function loadSaved(defaults: Settings): Settings {
	try {
		const raw = localStorage.getItem(STORE_KEY);
		let saved: Partial<Settings> = raw ? JSON.parse(raw) : {};
		if (!raw) {
			for (const [key, reset] of OLDER) {
				const old = localStorage.getItem(key);
				if (!old) continue;
				saved = JSON.parse(old);
				for (const k of reset) delete saved[k];
				break;
			}
		}
		return {
			...defaults,
			...saved,
			role_colors: { ...defaults.role_colors, ...(saved.role_colors ?? {}) },
			excluded: Array.isArray(saved.excluded) ? saved.excluded : defaults.excluded,
			excluded_colors: Array.isArray(saved.excluded_colors) ? saved.excluded_colors : defaults.excluded_colors,
			printed: saved.printed && typeof saved.printed === 'object' ? saved.printed : defaults.printed
		};
	} catch {
		return defaults;
	}
}

/** Drop saved values the server no longer offers (a printer removed, a filament renamed). */
function reconcile(s: Settings, o: Options): Settings {
	const printer = o.printers.find((p) => p.id === s.printer) ?? o.printers.find((p) => p.id === o.defaults.printer) ?? o.printers[0];
	return adjust(
		{
			...s,
			printer: printer.id,
			infill_pattern: o.infill_patterns.includes(s.infill_pattern) ? s.infill_pattern : o.defaults.infill_pattern,
			layers: Array.isArray(s.layers) ? s.layers : o.defaults.layers
		},
		o
	);
}

export default function App() {
	const [options, setOptions] = useState<Options | null>(null);
	const [settings, setSettings] = useState<Settings | null>(null);
	const [bom, setBom] = useState<Bom | null>(null);
	const [loadError, setLoadError] = useState<string | null>(null);
	const [job, setJob] = useState<Job | null>(null);
	const [jobSettings, setJobSettings] = useState<string | null>(null);
	const [buildError, setBuildError] = useState<string | null>(null);
	const poll = useRef<number | null>(null);
	// the colours in the parts list, to carry the colour filter to a new palette
	const usedColors = useRef<string[] | undefined>(undefined);
	useEffect(() => {
		usedColors.current = bom?.colors.map((c) => c.id);
	}, [bom]);

	useEffect(() => {
		getOptions()
			.then((o) => {
				setOptions(o);
				setSettings(reconcile(loadSaved(o.defaults), o));
			})
			.catch((e: Error) => setLoadError(e.message));
	}, []);

	useEffect(() => {
		if (!settings) return;
		try {
			localStorage.setItem(STORE_KEY, JSON.stringify(settings));
		} catch {
			/* storage disabled */
		}
		const ctl = new AbortController();
		const t = window.setTimeout(() => {
			getBom(settings, ctl.signal)
				.then(setBom)
				.catch((e: Error) => {
					if (e.name !== 'AbortError') setLoadError(e.message);
				});
		}, 150);
		return () => {
			window.clearTimeout(t);
			ctl.abort();
		};
	}, [settings]);

	useEffect(() => () => {
		if (poll.current) window.clearInterval(poll.current);
	}, []);

	// every change goes through adjust(): a new filament moves the colours to
	// its palette and the plate type to one it can print on
	const update = useCallback(
		(patch: Partial<Settings>) => setSettings((s) => (s && options ? adjust({ ...s, ...patch }, options, s, usedColors.current) : s)),
		[options]
	);

	const build = async () => {
		if (!settings) return;
		setBuildError(null);
		try {
			const { id } = await startJob(settings);
			setJobSettings(JSON.stringify(settings));
			setJob({ id, status: 'queued', stage: 'queued', progress: 0, message: 'Starting', error: null });
			if (poll.current) window.clearInterval(poll.current);
			poll.current = window.setInterval(async () => {
				try {
					const j = await getJob(id);
					setJob(j);
					if (j.status === 'done' || j.status === 'failed') {
						window.clearInterval(poll.current!);
						poll.current = null;
					}
				} catch (e) {
					window.clearInterval(poll.current!);
					poll.current = null;
					setBuildError((e as Error).message);
				}
			}, 600);
		} catch (e) {
			setBuildError((e as Error).message);
		}
	};

	const busy = !!job && (job.status === 'queued' || job.status === 'running');
	const stale = !!jobSettings && !!settings && jobSettings !== JSON.stringify(settings);

	return (
		<>
			<header className="topbar">
				<div className="brand">
					<strong>Sorter V2</strong>
					<span className="muted">3D print helper</span>
				</div>
				{options ? (
					<nav className="topbar-links small">
						<a className="muted" href="https://parts-calculator.basically.website/" target="_blank" rel="noreferrer">
							Parts from the Sorter V2 parts calculator
						</a>
						{options.source_url ? (
							<a className="muted" href={options.source_url} target="_blank" rel="noreferrer">
								Source code (AGPL-3.0)
							</a>
						) : null}
					</nav>
				) : null}
			</header>
			{loadError ? <div className="callout danger page-callout">Could not reach the backend: {loadError}</div> : null}
			{!options || !settings ? (
				!loadError ? <p className="page-loading muted">Loading the catalog…</p> : null
			) : (
				<main className="layout">
					<div className="col side">
						<MachinePanel settings={settings} options={options} update={update} />
						<SelectionTree bom={bom} options={options} settings={settings} update={update} />
						<ColorsPanel settings={settings} options={options} update={update} />
						<PrintPanel settings={settings} options={options} update={update} />
					</div>
					<div className="col main">
						<BuildPanel
							bom={bom}
							options={options}
							job={job}
							busy={busy}
							stale={stale}
							error={buildError}
							onBuild={build}
							heavier={settings.infill_density !== 15 || settings.infill_pattern !== 'adaptivecubic' || (settings.wall_loops ?? 2) !== 2}
						/>
						<PlatesPanel job={job} />
						<PartsTable bom={bom} options={options} settings={settings} update={update} />
					</div>
				</main>
			)}
		</>
	);
}
