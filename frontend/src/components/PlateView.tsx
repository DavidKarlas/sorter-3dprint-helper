import type { BuildResult, PlateOut } from '../types';

/** Top view of one plate: each part's footprint outline where the packer put it. */
export function PlateView({ plate, result }: { plate: PlateOut; result: BuildResult }) {
	const { width, depth, exclude } = result.bed;
	const stroke = shade(plate.color.hex);
	return (
		<svg className="plate-svg" viewBox={`0 0 ${width} ${depth}`} role="img" aria-label={`${plate.name}: ${plate.pieces.length} parts`}>
			<rect x={0} y={0} width={width} height={depth} className="bed" />
			{exclude.map(([x, y, w, h], i) => (
				<rect key={i} x={x} y={depth - y - h} width={w} height={h} className="bed-exclude" />
			))}
			{plate.pieces.map((p, i) => {
				const hull = result.footprints[p.part_id];
				// bed y points away from the viewer; SVG y points down
				const transform = `translate(${p.x} ${depth - p.y}) scale(1 -1) rotate(${p.rotation})`;
				return (
					<g key={i} transform={transform}>
						<title>{p.name}</title>
						{hull && hull.length > 2 ? (
							<polygon points={hull.map(([x, y]) => `${x},${y}`).join(' ')} fill={plate.color.hex} stroke={stroke} strokeWidth={1} />
						) : (
							<rect x={-p.w / 2} y={-p.d / 2} width={p.w} height={p.d} fill={plate.color.hex} stroke={stroke} strokeWidth={1} />
						)}
					</g>
				);
			})}
		</svg>
	);
}

function shade(hex: string): string {
	const h = hex.replace('#', '');
	const [r, g, b] = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
	const light = 0.299 * r + 0.587 * g + 0.114 * b > 140;
	const f = (v: number) => Math.round(light ? v * 0.55 : v + (255 - v) * 0.45);
	return `rgb(${f(r)}, ${f(g)}, ${f(b)})`;
}
