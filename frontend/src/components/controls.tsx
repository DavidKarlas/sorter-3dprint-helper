import { useEffect, useId, useRef, useState, type ReactNode } from 'react';
import type { Color } from '../types';

export function Panel({ title, actions, children }: { title: string; actions?: ReactNode; children: ReactNode }) {
	return (
		<section className="panel">
			<header className="panel-head">
				<h2>{title}</h2>
				{actions ? <div className="panel-actions">{actions}</div> : null}
			</header>
			{children}
		</section>
	);
}

export function Row({ label, hint, children }: { label: string; hint?: ReactNode; children: ReactNode }) {
	const id = useId();
	return (
		<div className="row" role="group" aria-labelledby={id}>
			<div className="row-label">
				<span id={id}>{label}</span>
				{hint ? <div className="hint">{hint}</div> : null}
			</div>
			<div className="row-control">{children}</div>
		</div>
	);
}

export function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
	return (
		<label className="toggle">
			<input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
			<span>{label}</span>
		</label>
	);
}

export function Segmented<T extends string>({
	value,
	options,
	onChange,
	label
}: {
	value: T;
	options: { value: T; label: string }[];
	onChange: (v: T) => void;
	label: string;
}) {
	return (
		<div className="segmented" role="radiogroup" aria-label={label}>
			{options.map((o) => (
				<button
					key={o.value}
					type="button"
					role="radio"
					aria-checked={o.value === value}
					className={o.value === value ? 'on' : ''}
					onClick={() => onChange(o.value)}
				>
					{o.label}
				</button>
			))}
		</div>
	);
}

export function NumberField({
	value,
	onChange,
	min,
	max,
	step = 1,
	suffix,
	placeholder
}: {
	value: number | null;
	onChange: (v: number | null) => void;
	min?: number;
	max?: number;
	step?: number;
	suffix?: string;
	placeholder?: string;
}) {
	const [text, setText] = useState(value === null ? '' : String(value));
	useEffect(() => setText(value === null ? '' : String(value)), [value]);
	return (
		<span className="number-field">
			<input
				type="number"
				inputMode="decimal"
				value={text}
				min={min}
				max={max}
				step={step}
				placeholder={placeholder}
				onChange={(e) => setText(e.target.value)}
				onBlur={() => {
					if (text.trim() === '') return onChange(null);
					let n = Number(text);
					if (!Number.isFinite(n)) return setText(value === null ? '' : String(value));
					if (min !== undefined) n = Math.max(min, n);
					if (max !== undefined) n = Math.min(max, n);
					onChange(n);
				}}
				onKeyDown={(e) => {
					if (e.key === 'Enter') (e.target as HTMLInputElement).blur();
				}}
			/>
			{suffix ? <span className="suffix">{suffix}</span> : null}
		</span>
	);
}

export function Swatch({ hex, title, size = 14 }: { hex: string; title?: string; size?: number }) {
	return <span className="swatch" style={{ background: hex, width: size, height: size }} title={title} />;
}

export function ColorPicker({
	value,
	colors,
	onChange,
	label
}: {
	value: string;
	colors: Color[];
	onChange: (id: string) => void;
	label: string;
}) {
	const [open, setOpen] = useState(false);
	const ref = useRef<HTMLDivElement>(null);
	const current = colors.find((c) => c.id === value);
	useEffect(() => {
		if (!open) return;
		const close = (e: MouseEvent) => {
			if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
		};
		const esc = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false);
		document.addEventListener('mousedown', close);
		document.addEventListener('keydown', esc);
		return () => {
			document.removeEventListener('mousedown', close);
			document.removeEventListener('keydown', esc);
		};
	}, [open]);
	return (
		<div className="color-picker" ref={ref}>
			<button type="button" className="field-button" aria-haspopup="listbox" aria-expanded={open} aria-label={`${label}: ${current?.name ?? value}`} onClick={() => setOpen((o) => !o)}>
				<Swatch hex={current?.hex ?? '#999999'} />
				<span>{current?.name ?? value}</span>
			</button>
			{open ? (
				<div className="popover" role="listbox" aria-label={label}>
					{colors.map((c) => (
						<button
							key={c.id}
							type="button"
							role="option"
							aria-selected={c.id === value}
							className={c.id === value ? 'on' : ''}
							onClick={() => {
								onChange(c.id);
								setOpen(false);
							}}
						>
							<Swatch hex={c.hex} />
							<span>{c.name}</span>
						</button>
					))}
				</div>
			) : null}
		</div>
	);
}
