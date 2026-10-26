"use client";

import { useEffect, useMemo, useState } from "react";
import Image from "next/image";
import { fetcher, runMutation, useHeroes } from "@/lib/api";
import { PlayerBar, usePlayerSelection } from "@/components/player-context";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
	Dialog,
	DialogHeader,
	DialogTitle,
	DialogDescription,
	DialogFooter,
} from "@/components/ui/dialog";
import {
	Check,
	Plus,
	Trash2,
	Sparkles,
	Save,
	Search,
	Shirt,
	UserRound,
	Loader2,
} from "lucide-react";

type Hero = {
	unitId: number;
	name: string;
	role: string;
	skins: number;
	isDimensionUnit?: boolean;
	level: number;
	exp: number;
	soul: number;
	potentialTier: number;
	overcome?: number;
	dimensionLevel?: number;
};
type HeroesResponse = { owned: Hero[]; missing: Hero[] };

const ROLE_STYLE: Record<
	string,
	{ badge: string; avatar: string; label: string }
> = {
	Warrior: {
		badge:
			"bg-orange-50 text-orange-700 border-orange-200 dark:bg-orange-500/15 dark:text-orange-400 dark:border-orange-500/30",
		avatar: "from-orange-500 to-rose-600",
		label: "W",
	},
	Archer: {
		badge:
			"bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-500/15 dark:text-emerald-400 dark:border-emerald-500/30",
		avatar: "from-emerald-500 to-teal-600",
		label: "A",
	},
	Mage: {
		badge:
			"bg-blue-50 text-blue-700 border-blue-200 dark:bg-blue-500/15 dark:text-blue-400 dark:border-blue-500/30",
		avatar: "from-blue-500 to-indigo-600",
		label: "M",
	},
	Priest: {
		badge:
			"bg-cyan-50 text-cyan-700 border-cyan-200 dark:bg-cyan-500/15 dark:text-cyan-400 dark:border-cyan-500/30",
		avatar: "from-cyan-500 to-sky-600",
		label: "P",
	},
	Assassin: {
		badge:
			"bg-purple-50 text-purple-700 border-purple-200 dark:bg-purple-500/15 dark:text-purple-400 dark:border-purple-500/30",
		avatar: "from-purple-500 to-fuchsia-600",
		label: "A",
	},
};

const DIM_BADGE =
	"bg-violet-50 text-violet-700 border-violet-200 dark:bg-violet-500/15 dark:text-violet-400 dark:border-violet-500/30";

function roleStyle(role: string) {
	return (
		ROLE_STYLE[role] || {
			badge:
				"bg-slate-50 text-slate-600 border-slate-200 dark:bg-slate-500/15 dark:text-slate-300 dark:border-slate-500/30",
			avatar: "from-slate-500 to-slate-700",
			label: "?",
		}
	);
}

function Avatar({
	name,
	role,
	unitId,
	size = "h-12 w-12 text-lg",
}: {
	name: string;
	role: string;
	unitId: number;
	size?: string;
}) {
	const style = roleStyle(role);
	const [broken, setBroken] = useState(false);
	const letter = (name || "?").charAt(0).toUpperCase();
	if (!broken) {
		return (
			<Image
				src={`/assets/heroes/${unitId}.webp`}
				alt={name}
				title={name}
				width={48}
				height={48}
				unoptimized
				onError={() => setBroken(true)}
				className={`${size} shrink-0 rounded-full border border-border bg-muted object-cover shadow`}
			/>
		);
	}
	return (
		<div
			className={`flex ${size} shrink-0 items-center justify-center rounded-full bg-gradient-to-br font-bold text-white shadow ${style.avatar}`}
		>
			{letter}
		</div>
	);
}

export default function HeroesPage() {
	const { selectedId } = usePlayerSelection();
	const { data, mutate, isLoading } = useHeroes(selectedId || undefined);
	const [query, setQuery] = useState("");

	return (
		<div className="space-y-6">
			<div>
				<h1 className="text-2xl font-semibold tracking-tight">Heroes</h1>
				<p className="text-muted-foreground">
					Edit levels, souls and awakening tiers of owned heroes; grant missing
					ones.
				</p>
			</div>
			<PlayerBar />
			{selectedId && data && (
				<div className="relative -mt-2 max-w-sm">
					<Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
					<Input
						value={query}
						onChange={(e) => setQuery(e.target.value)}
						placeholder="Search heroes by name or id..."
						className="pl-8"
					/>
				</div>
			)}
			{!selectedId && (
				<Card>
					<CardContent className="py-16 text-center text-muted-foreground">
						Select a player above.
					</CardContent>
				</Card>
			)}
			{selectedId && isLoading && !data && (
				<Card>
					<CardContent className="py-16 flex flex-col items-center justify-center gap-3 text-muted-foreground">
						<Loader2 className="h-8 w-8 animate-spin text-primary" />
						<p className="text-sm font-medium">Loading heroes...</p>
					</CardContent>
				</Card>
			)}
			{selectedId && data && (
				<>
					<OwnedGrid data={data} onMutate={mutate} query={query} />
					<MissingGrid data={data} onMutate={mutate} query={query} />
				</>
			)}
		</div>
	);
}

function matchesQuery(h: { name: string; unitId: number }, query: string) {
	const q = query.trim().toLowerCase();
	if (!q) return true;
	return h.name.toLowerCase().includes(q) || String(h.unitId).includes(q);
}

function OwnedGrid({
	data,
	onMutate,
	query,
}: {
	data: HeroesResponse;
	onMutate: () => void;
	query: string;
}) {
	const { selectedId } = usePlayerSelection();
	const [drafts, setDrafts] = useState<Record<string, Record<string, string>>>(
		{},
	);
	const [skinHero, setSkinHero] = useState<Hero | null>(null);

	const owned = useMemo(
		() => data.owned.filter((h) => matchesQuery(h, query)),
		[data.owned, query],
	);

	const grantAllSkins = async () => {
		await runMutation(
			`/api/player/${encodeURIComponent(selectedId!)}/grant-all-skins`,
			{ method: "POST" },
			"All skins granted to every hero",
		);
		onMutate();
	};

	const setField = (unitId: number, key: string, value: string) =>
		setDrafts((prev) => ({
			...prev,
			[unitId]: { ...(prev[unitId] || {}), [key]: value },
		}));

	const save = async (hero: Hero) => {
		const draft = drafts[hero.unitId] || {};
		const patch: Record<string, number> = {};
		for (const [k, v] of Object.entries(draft)) {
			const n = Number(v);
			if (!Number.isNaN(n) && n !== hero[k as keyof Hero]) patch[k] = n;
		}
		if (!Object.keys(patch).length) return;
		await runMutation(
			`/api/player/${encodeURIComponent(selectedId!)}/heroes/${hero.unitId}`,
			{ method: "PATCH", body: JSON.stringify(patch) },
			`Hero ${hero.unitId} updated`,
		);
		setDrafts((prev) => {
			const rest = { ...prev };
			delete rest[hero.unitId];
			return rest;
		});
		onMutate();
	};

	const remove = async (hero: Hero) => {
		if (!window.confirm(`Remove hero ${hero.unitId} (${hero.name})?`)) return;
		await runMutation(
			`/api/player/${encodeURIComponent(selectedId!)}/heroes/${hero.unitId}`,
			{ method: "DELETE" },
			"Hero removed",
		);
		onMutate();
	};

	const field = (h: Hero, key: keyof Hero, w = "w-16") => {
		const d = drafts[h.unitId] || {};
		const inputId = `hero-${h.unitId}-${String(key)}`;
		return (
			<div className="space-y-0.5">
				<label
					htmlFor={inputId}
					className="block text-[10px] uppercase tracking-wide text-muted-foreground"
				>
					{key}
				</label>
				<Input
					id={inputId}
					type="number"
					className={`h-8 ${w} font-mono tnum`}
					value={d[key] ?? h[key]}
					onChange={(e) => setField(h.unitId, key, e.target.value)}
				/>
			</div>
		);
	};

	return (
		<div>
			<div className="mb-3 flex items-center justify-between gap-3">
				<h2 className="flex items-center gap-2 text-base font-semibold">
					<UserRound className="h-4 w-4 text-muted-foreground" /> Owned (
					{owned.length}
					{query.trim() && ` of ${data.owned.length}`})
				</h2>
				<Button variant="outline" size="sm" onClick={grantAllSkins}>
					<Shirt className="h-3.5 w-3.5" /> All skins
				</Button>
			</div>
			{!owned.length && (
				<Card>
					<CardContent className="py-6 text-sm text-muted-foreground">
						No owned heroes match the search.
					</CardContent>
				</Card>
			)}
			<div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
				{owned.map((h) => {
					const style = roleStyle(h.role);
					return (
						<Card key={h.unitId} className="p-0">
							<CardContent className="p-3">
								<div className="flex items-start gap-3">
									<Avatar name={h.name} role={h.role} unitId={h.unitId} />
									<div className="min-w-0 flex-1">
										<div className="flex items-center gap-2">
											<span className="truncate text-sm font-semibold">
												{h.name}
											</span>
											<Badge
												className={`shrink-0 ${style.badge}`}
												variant="outline"
											>
												{h.role}
											</Badge>
											{h.isDimensionUnit && (
												<Badge
													className={`shrink-0 ${DIM_BADGE}`}
													variant="outline"
												>
													Dim
												</Badge>
											)}
										</div>
										<div className="text-xs text-muted-foreground font-mono">
											#{h.unitId} · {h.skins} skins
										</div>
									</div>
								</div>
								<div className="mt-3 flex flex-wrap items-end gap-2">
									{field(h, "level")}
									{field(h, "exp", "w-20")}
									{field(h, "soul")}
									{field(h, "potentialTier", "w-24")}
									{h.isDimensionUnit && (
										<>
											{field(h, "overcome", "w-16")}
											{field(h, "dimensionLevel", "w-16")}
										</>
									)}
									<div className="ml-auto flex gap-1">
										<Button
											variant="outline"
											size="icon"
											className="h-8 w-8"
											title="Manage skins"
											onClick={() => setSkinHero(h)}
										>
											<Shirt className="h-3.5 w-3.5" />
										</Button>
										<Button
											variant="outline"
											size="icon"
											className="h-8 w-8"
											title="Save"
											onClick={() => save(h)}
										>
											<Save className="h-3.5 w-3.5" />
										</Button>
										<Button
											variant="outline"
											size="icon"
											className="h-8 w-8 text-destructive"
											title="Remove"
											onClick={() => remove(h)}
										>
											<Trash2 className="h-3.5 w-3.5" />
										</Button>
									</div>
								</div>
							</CardContent>
						</Card>
					);
				})}
			</div>
			{skinHero && (
				<SkinDialog
					hero={skinHero}
					onClose={() => setSkinHero(null)}
					onMutate={onMutate}
				/>
			)}
		</div>
	);
}

// --- per-hero skin manager ---------------------------------------------------
type SkinEntry = {
	id: number;
	owned: boolean;
	name?: string;
	grade?: string | null;
	image?: string | null;
};

function SkinDialog({
	hero,
	onClose,
	onMutate,
}: {
	hero: Hero;
	onClose: () => void;
	onMutate: () => void;
}) {
	const { selectedId } = usePlayerSelection();
	const [skins, setSkins] = useState<SkinEntry[] | null>(null);
	const [busy, setBusy] = useState(false);
	const base = `/api/player/${encodeURIComponent(selectedId!)}/heroes/${hero.unitId}/skins`;

	const load = () =>
		fetcher(base)
			.then((d: { skins: SkinEntry[] }) => setSkins(d.skins))
			.catch(() => setSkins([]));

	useEffect(() => {
		load();
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, []);

	const toggle = async (s: SkinEntry) => {
		setBusy(true);
		try {
			if (s.owned) {
				await runMutation(`${base}/${s.id}`, { method: "DELETE" }, "Skin revoked");
			} else {
				await runMutation(
					base,
					{ method: "POST", body: JSON.stringify({ skinId: s.id }) },
					`${s.name || `Skin ${s.id}`} granted`,
				);
			}
			await load();
			onMutate();
		} catch {
			/* runMutation already surfaced the toast */
		}
		setBusy(false);
	};

	const grantMissing = async () => {
		const ids = (skins || []).filter((s) => !s.owned).map((s) => s.id);
		if (!ids.length) return;
		setBusy(true);
		try {
			await runMutation(
				base,
				{ method: "POST", body: JSON.stringify({ skinIds: ids }) },
				`${ids.length} skin(s) granted`,
			);
			await load();
			onMutate();
		} catch {
			/* runMutation already surfaced the toast */
		}
		setBusy(false);
	};

	const ownedCount = (skins || []).filter((s) => s.owned).length;
	const missingCount = (skins || []).filter((s) => !s.owned).length;

	return (
		<Dialog open onClose={onClose} wide>
			<DialogHeader onClose={onClose}>
				<DialogTitle>Skins · {hero.name}</DialogTitle>
				<DialogDescription>
					Grant or revoke individual skins for hero #{hero.unitId}. The client
					picks them up on its next fetch.
				</DialogDescription>
			</DialogHeader>
			<div className="max-h-[55vh] overflow-y-auto px-5 py-4">
				{!skins ? (
					<div className="flex items-center justify-center gap-2 py-10 text-muted-foreground">
						<Loader2 className="h-5 w-5 animate-spin text-primary" />
						Loading skins...
					</div>
				) : !skins.length ? (
					<div className="py-10 text-center text-sm text-muted-foreground">
						No skins exist for this hero in master data.
					</div>
				) : (
					<div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
						{skins.map((s) => (
							<div
								key={s.id}
								className={`flex items-center gap-2.5 rounded-lg border p-2 ${
									s.owned
										? "border-emerald-200 bg-emerald-50/50 dark:border-emerald-500/30 dark:bg-emerald-500/10"
										: "border-border bg-card"
								}`}
							>
								{s.image ? (
									<Image
										src={s.image}
										alt={s.name || String(s.id)}
										width={48}
										height={48}
										unoptimized
										className="h-12 w-12 shrink-0 rounded-md border border-border bg-muted object-cover"
									/>
								) : (
									<div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-md border border-border bg-muted">
										<Shirt className="h-5 w-5 text-muted-foreground" />
										</div>
								)}
								<div className="min-w-0 flex-1">
									<div className="truncate text-sm font-medium">
										{s.name || `Skin ${s.id}`}
									</div>
									<div className="flex items-center gap-1.5">
										<span className="font-mono text-xs text-muted-foreground">
											#{s.id}
										</span>
										{s.grade && (
											<Badge variant="neutral" className="px-1.5 py-0 text-[10px]">
												{s.grade}
											</Badge>
										)}
									</div>
								</div>
								<Button
									variant={s.owned ? "ghost" : "outline"}
									size="sm"
									className="shrink-0"
									disabled={busy}
									onClick={() => toggle(s)}
								>
									{s.owned ? (
										<>
											<Check className="h-3.5 w-3.5" /> Owned
										</>
									) : (
										<>
											<Plus className="h-3.5 w-3.5" /> Grant
										</>
									)}
								</Button>
							</div>
						))}
					</div>
				)}
			</div>
			<DialogFooter>
				<span className="mr-auto text-xs text-muted-foreground">
					{ownedCount}/{(skins || []).length} owned
				</span>
				<Button variant="outline" size="sm" onClick={onClose}>
					Close
				</Button>
				<Button size="sm" disabled={busy || !missingCount} onClick={grantMissing}>
					<Sparkles className="h-3.5 w-3.5" /> Grant all missing
				</Button>
			</DialogFooter>
		</Dialog>
	);
}

function MissingGrid({
	data,
	onMutate,
	query,
}: {
	data: HeroesResponse;
	onMutate: () => void;
	query: string;
}) {
	const { selectedId } = usePlayerSelection();
	const [level, setLevel] = useState("30");
	const [soul, setSoul] = useState("999");
	const [overcome, setOvercome] = useState("0");
	const [dimLevel, setDimLevel] = useState("0");

	const missing = useMemo(
		() => data.missing.filter((h) => matchesQuery(h, query)),
		[data.missing, query],
	);

	const grant = async (h: Hero) => {
		await runMutation(
			`/api/player/${encodeURIComponent(selectedId!)}/heroes/${h.unitId}`,
			{ method: "POST" },
			`${h.name} granted`,
		);
		onMutate();
	};

	const grantAll = async () => {
		await runMutation(
			`/api/player/${encodeURIComponent(selectedId!)}/heroes-grant-all`,
			{
				method: "POST",
				body: JSON.stringify({
					level: Number(level),
					soul: Number(soul),
					overcome: Number(overcome),
					dimensionLevel: Number(dimLevel),
				}),
			},
			"All missing heroes granted",
		);
		onMutate();
	};

	if (!data.missing.length)
		return (
			<Card>
				<CardContent className="py-6 flex items-center gap-2 text-muted-foreground">
					<Check className="h-4 w-4" /> Every hero in master data is owned.
				</CardContent>
			</Card>
		);

	return (
		<div>
			<div className="mb-3 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
				<h2 className="flex items-center gap-2 text-base font-semibold">
					<Sparkles className="h-4 w-4 text-muted-foreground" /> Missing (
					{missing.length}
					{query.trim() && ` of ${data.missing.length}`})
				</h2>
				<div className="flex flex-wrap items-end gap-2">
					<div className="space-y-0.5">
						<label
							htmlFor="grant-level"
							className="block text-[10px] uppercase tracking-wide text-muted-foreground"
						>
							Level
						</label>
						<Input
							id="grant-level"
							type="number"
							className="h-8 w-20 font-mono tnum"
							value={level}
							onChange={(e) => setLevel(e.target.value)}
						/>
					</div>
					<div className="space-y-0.5">
						<label
							htmlFor="grant-soul"
							className="block text-[10px] uppercase tracking-wide text-muted-foreground"
						>
							Soul
						</label>
						<Input
							id="grant-soul"
							type="number"
							className="h-8 w-20 font-mono tnum"
							value={soul}
							onChange={(e) => setSoul(e.target.value)}
						/>
					</div>
					<div className="space-y-0.5">
						<label
							htmlFor="grant-overcome"
							className="block text-[10px] uppercase tracking-wide text-muted-foreground"
						>
							Overcome
						</label>
						<Input
							id="grant-overcome"
							type="number"
							className="h-8 w-16 font-mono tnum"
							value={overcome}
							onChange={(e) => setOvercome(e.target.value)}
						/>
					</div>
					<div className="space-y-0.5">
						<label
							htmlFor="grant-dimlevel"
							className="block text-[10px] uppercase tracking-wide text-muted-foreground"
						>
							Dim Level
						</label>
						<Input
							id="grant-dimlevel"
							type="number"
							className="h-8 w-16 font-mono tnum"
							value={dimLevel}
							onChange={(e) => setDimLevel(e.target.value)}
						/>
					</div>
					<Button size="sm" onClick={grantAll}>
						<Sparkles className="h-3.5 w-3.5 mr-1" /> Grant all
					</Button>
				</div>
			</div>
			<div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
				{missing.map((h) => {
					const style = roleStyle(h.role);
					return (
						<Card key={h.unitId} className="p-0">
							<CardContent className="flex items-center gap-3 p-3">
								<Avatar
									name={h.name}
									role={h.role}
									unitId={h.unitId}
									size="h-10 w-10 text-base"
								/>
								<div className="min-w-0 flex-1">
									<div className="flex items-center gap-2">
										<span className="truncate text-sm font-semibold">
											{h.name}
										</span>
										<Badge
											className={`shrink-0 ${style.badge}`}
											variant="outline"
										>
											{h.role}
										</Badge>
										{h.isDimensionUnit && (
											<Badge
												className={`shrink-0 ${DIM_BADGE}`}
												variant="outline"
											>
												Dim
											</Badge>
										)}
									</div>
									<div className="text-xs text-muted-foreground font-mono">
										#{h.unitId}
									</div>
								</div>
								<Button variant="outline" size="sm" onClick={() => grant(h)}>
									<Plus className="h-3.5 w-3.5 mr-1" /> Grant
								</Button>
							</CardContent>
						</Card>
					);
				})}
			</div>
		</div>
	);
}
