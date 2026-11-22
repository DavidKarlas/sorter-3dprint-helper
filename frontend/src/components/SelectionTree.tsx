import { useEffect, useRef, useState } from 'react';
import type { Bom, Options, Settings, TreeNode } from '../types';
import { Panel } from './controls';

type Props = {
	bom: Bom | null;
	options: Options;
	settings: Settings;
	update: (patch: Partial<Settings>) => void;
};

/** Every leaf key under a node (a leaf is what a checkbox really switches). */
function leaves(node: TreeNode): string[] {
	return node.children.length ? node.children.flatMap(leaves) : [node.key];
}

/** The machine's assembly tree as checkboxes: Feeder, C-channel 1, C-channel 2... */
export function SelectionTree({ bom, options, settings, update }: Props) {
	const root = bom?.tree;
	const [open, setOpen] = useState<Set<string>>(() => new Set(['machine/feeder', 'machine/superstructure', 'machine/electronics']));

	const toggle = (node: TreeNode) => {
		const keys = leaves(node);
		const excluded = new Set(settings.excluded);
		const allOn = node.selected === node.total;
		if (allOn) keys.forEach((k) => excluded.add(k));
		else {
			keys.forEach((k) => excluded.delete(k));
			// a place above this one may have been switched off as a whole
			for (const k of [...excluded]) if (node.key.startsWith(k + '/') || node.key === k) excluded.delete(k);
		}
		update({ excluded: [...excluded].sort() });
	};

	const expand = (key: string) =>
		setOpen((o) => {
			const n = new Set(o);
			if (n.has(key)) n.delete(key);
			else n.add(key);
			return n;
		});

	return (
		<Panel
			title="What to print"
			actions={
				root ? (
					<>
						<button type="button" className="link-button" onClick={() => update({ excluded: [] })}>
							All
						</button>
						<button type="button" className="link-button" onClick={() => update({ excluded: leaves(root).sort() })}>
							None
						</button>
						<button type="button" className="link-button" onClick={() => update({ excluded: [...options.defaults.excluded] })}>
							Default
						</button>
					</>
				) : null
			}
		>
			<p className="panel-note">
				Tick the parts of the machine to print. Counts are pieces: selected of total.
				{root ? (
					<>
						{' '}
						<b className="ink">
							{root.selected} of {root.total}
						</b>{' '}
						selected.
					</>
				) : null}
			</p>
			{!root ? (
				<p className="panel-note">Loading…</p>
			) : (
				<ul className="tree" role="tree">
					{root.children.map((n) => (
						<Node key={n.key} node={n} depth={0} open={open} onToggle={toggle} onExpand={expand} />
					))}
				</ul>
			)}
		</Panel>
	);
}

function Node({
	node,
	depth,
	open,
	onToggle,
	onExpand
}: {
	node: TreeNode;
	depth: number;
	open: Set<string>;
	onToggle: (n: TreeNode) => void;
	onExpand: (key: string) => void;
}) {
	const box = useRef<HTMLInputElement>(null);
	const state = node.selected === 0 ? 'off' : node.selected === node.total ? 'on' : 'some';
	useEffect(() => {
		if (box.current) box.current.indeterminate = state === 'some';
	}, [state]);
	const hasKids = node.children.length > 0;
	const isOpen = open.has(node.key);
	const title = node.parts.length ? node.parts.join(', ') : undefined;
	return (
		<li role="treeitem" aria-expanded={hasKids ? isOpen : undefined} aria-selected={state === 'on'}>
			<div className={`tree-row ${state}`} style={{ paddingLeft: depth * 16 }}>
				{hasKids ? (
					<button type="button" className="tree-chevron" aria-label={isOpen ? `Collapse ${node.name}` : `Expand ${node.name}`} onClick={() => onExpand(node.key)}>
						<span className={isOpen ? 'open' : ''}>›</span>
					</button>
				) : (
					<span className="tree-chevron" />
				)}
				<label className="tree-label" title={title}>
					<input ref={box} type="checkbox" checked={state === 'on'} onChange={() => onToggle(node)} />
					<span className="tree-name">
						{node.name}
						{node.mult > 1 ? <span className="faint"> ×{node.mult}</span> : null}
					</span>
				</label>
				<span className="tree-count">{state === 'on' ? node.total : `${node.selected}/${node.total}`}</span>
			</div>
			{hasKids && isOpen ? (
				<ul role="group">
					{node.children.map((c) => (
						<Node key={c.key} node={c} depth={depth + 1} open={open} onToggle={onToggle} onExpand={onExpand} />
					))}
				</ul>
			) : null}
		</li>
	);
}
