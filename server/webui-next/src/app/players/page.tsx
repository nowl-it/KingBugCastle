"use client";

import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
	usePlayers,
	usePlayer,
	usePlayerRaw,
	runMutation,
	fetcher,
} from "@/lib/api";
import { usePlayerSelection } from "@/components/player-context";
import {
	Card,
	CardContent,
	CardHeader,
	CardTitle,
	CardDescription,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Select } from "@/components/ui/select";
import {
	Dialog,
	DialogContent,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import {
	Table,
	TableBody,
	TableCell,
	TableHead,
	TableHeader,
	TableRow,
} from "@/components/ui/table";
import {
	Search,
	Plus,
	Copy,
	Trash2,
	Save,
	RefreshCw,
	Zap,
	X,
	UserCheck,
	ChevronDown,
	ChevronRight,
} from "lucide-react";

type PlayerSummary = {
	id: string;
	uid?: string;
	name: string;
	castleName?: string;
	active?: boolean;
	level?: number;
	gold?: number;
	cash?: number;
	heart?: number;
	lastActive?: number;
	counts?: { cards?: number; posts?: number; items?: number };
	[key: string]:
		| string
		| number
		| boolean
		| undefined
		| { cards?: number; posts?: number; items?: number };
};
type PlayerDetailResponse = { summary: PlayerSummary };

const EDITABLE_FIELDS: Record<string, { label: string; type?: string }> = {
	name: { label: "Name" },
	castleName: { label: "Castle name" },
	gold: { label: "Gold", type: "number" },
	cash: { label: "Cash", type: "number" },
	heart: { label: "Heart", type: "number" },
	level: { label: "Account level", type: "number" },
	exp: { label: "Exp", type: "number" },
	bestClearedStage: { label: "Best stage", type: "number" },
	bestClearedTheme: { label: "Best theme", type: "number" },
	bestClearedHardStage: { label: "Best hard stage", type: "number" },
	bestClearedHardTheme: { label: "Best hard theme", type: "number" },
	buildingPoints: { label: "Building points", type: "number" },
	playedCount: { label: "Battles played", type: "number" },
	winCount: { label: "Battles won", type: "number" },
};

type SortKey = "name" | "level" | "gold" | "lastActive";

function timeAgo(ts?: number) {
	if (!ts) return "-";
	const s = Math.max(0, Date.now() / 1000 - ts);
	if (s < 90) return "just now";
	if (s < 3600) return `${Math.round(s / 60)}m ago`;
	if (s < 86400) return `${Math.round(s / 3600)}h ago`;
	return `${Math.round(s / 86400)}d ago`;
}

export default function PlayersPage() {
	const { data: players, mutate: mutatePlayers } = usePlayers();
	const { setSelectedId } = usePlayerSelection();
	const [query, setQuery] = useState("");
	const [sort, setSort] = useState<SortKey>("level");
	const [active24h, setActive24h] = useState(false);
	const [showCreate, setShowCreate] = useState(false);
	const [newName, setNewName] = useState("");
	const [newUid, setNewUid] = useState("");
	const [drawerPid, setDrawerPid] = useState<string | null>(null);
	const [checked, setChecked] = useState<Set<string>>(new Set());
	// Wall-clock snapshot updated on a timer so the 24h filter stays pure inside useMemo.
	const [now, setNow] = useState(() => Date.now());

	useEffect(() => {
		const id = setInterval(() => setNow(Date.now()), 30000);
		return () => clearInterval(id);
	}, []);

	const list = useMemo(() => {
		let arr = (Array.isArray(players) ? players : []) as PlayerSummary[];
		const q = query.trim().toLowerCase();
		if (q) {
			arr = arr.filter(
				(p) =>
					(p.name || "").toLowerCase().includes(q) ||
					(p.id || "").toLowerCase().includes(q) ||
					(p.uid || "").toLowerCase().includes(q) ||
					(p.castleName || "").toLowerCase().includes(q),
			);
		}
		if (active24h)
			arr = arr.filter(
				(p) => p.active || (p.lastActive && now / 1000 - p.lastActive < 86400),
			);
		return [...arr].sort((a, b) => {
			if (sort === "name") return (a.name || "").localeCompare(b.name || "");
			if (sort === "gold") return (b.gold || 0) - (a.gold || 0);
			if (sort === "lastActive")
				return (b.lastActive || 0) - (a.lastActive || 0);
			return (b.level || 0) - (a.level || 0);
		});
	}, [players, query, sort, active24h, now]);

	const toggleCheck = (pid: string) => {
		setChecked((prev) => {
			const next = new Set(prev);
			if (next.has(pid)) next.delete(pid);
			else next.add(pid);
			return next;
		});
	};
	const allChecked = list.length > 0 && list.every((p) => checked.has(p.id));
	const toggleAll = () =>
		setChecked(allChecked ? new Set() : new Set(list.map((p) => p.id)));

	const bulkMutate = async (
		url: string,
		body: Record<string, unknown>,
		msg: string,
	) => {
		await runMutation(
			url,
			{ method: "POST", body: JSON.stringify({ pids: [...checked], ...body }) },
			msg,
		);
		setChecked(new Set());
		mutatePlayers();
	};

	const handleCreate = async () => {
		if (!newName.trim()) return;
		await runMutation(
			"/api/players",
			{
				method: "POST",
				body: JSON.stringify({
					name: newName,
					uid: newUid.trim() || undefined,
				}),
			},
			"Player created",
		);
		setNewName("");
		setNewUid("");
		setShowCreate(false);
		mutatePlayers();
	};

	const openInHeroes = (pid: string) => {
		setSelectedId(pid);
	};

	return (
		<div className="space-y-5">
			<div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
				<div>
					<h1 className="text-2xl font-semibold tracking-tight">Players</h1>
					<p className="text-sm text-muted-foreground">
						{list.length} of {(Array.isArray(players) ? players : []).length}{" "}
						saves shown.
					</p>
				</div>
				<Button onClick={() => setShowCreate(true)}>
					<Plus className="h-4 w-4" /> New player
				</Button>
			</div>

			{/* Toolbar */}
			<div className="flex flex-wrap items-center gap-3">
				<div className="relative">
					<Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
					<Input
						placeholder="Search name / id / castle..."
						value={query}
						onChange={(e) => setQuery(e.target.value)}
						className="w-64 pl-8"
					/>
				</div>
				<Select
					value={sort}
					onChange={(e) => setSort(e.target.value as SortKey)}
					className="w-44"
				>
					<option value="level">Sort: level</option>
					<option value="gold">Sort: gold</option>
					<option value="lastActive">Sort: last active</option>
					<option value="name">Sort: name</option>
				</Select>
				<Button
					variant={active24h ? "primary" : "outline"}
					size="sm"
					onClick={() => setActive24h((v) => !v)}
				>
					Active 24h
				</Button>
			</div>

			<Card>
				<CardContent className="p-0">
					<Table compact>
						<TableHeader>
							<TableRow>
								<TableHead className="w-10">
									<input
										type="checkbox"
										aria-label="Select all"
										checked={allChecked}
										onChange={toggleAll}
										className="h-4 w-4 accent-[var(--primary)]"
									/>
								</TableHead>
								<TableHead>Player</TableHead>
								<TableHead>Castle</TableHead>
								<TableHead className="text-right">Level</TableHead>
								<TableHead className="text-right">Gold</TableHead>
								<TableHead className="text-right">Heroes</TableHead>
								<TableHead className="text-right">Last active</TableHead>
								<TableHead className="w-28" />
							</TableRow>
						</TableHeader>
						<TableBody>
							{list.map((p) => (
								<TableRow
									key={p.id}
									className="cursor-pointer"
									onClick={() => setDrawerPid(p.id)}
								>
									<TableCell>
										<input
											type="checkbox"
											aria-label={`Select ${p.name}`}
											checked={checked.has(p.id)}
											onClick={(e) => e.stopPropagation()}
											onChange={() => toggleCheck(p.id)}
											className="h-4 w-4 accent-[var(--primary)]"
										/>
									</TableCell>
									<TableCell>
										<div className="flex items-center gap-2">
											<span
												className={`h-2 w-2 shrink-0 rounded-full ${p.active ? "bg-success" : "bg-muted-foreground/30"}`}
											/>
											<div className="min-w-0">
												<div className="truncate font-medium">{p.name}</div>
												<div className="truncate font-mono text-xs text-muted-foreground">
													{p.id}
												</div>
											</div>
										</div>
									</TableCell>
									<TableCell className="max-w-[12rem] truncate text-muted-foreground">
										{p.castleName || "-"}
									</TableCell>
									<TableCell className="tnum text-right">{p.level}</TableCell>
									<TableCell className="tnum text-right">
										{(p.gold ?? 0).toLocaleString()}
									</TableCell>
									<TableCell className="tnum text-right">
										{p.counts?.cards ?? 0}
									</TableCell>
									<TableCell className="tnum text-right text-muted-foreground">
										{timeAgo(p.lastActive)}
									</TableCell>
									<TableCell>
										<div className="flex items-center justify-end gap-1">
											<Button
												variant="ghost"
												size="sm"
												title="Use in Heroes page"
												onClick={(e) => {
													e.stopPropagation();
													openInHeroes(p.id);
												}}
											>
												<UserCheck className="h-4 w-4" />
											</Button>
											<ChevronRight className="h-4 w-4 text-muted-foreground" />
										</div>
									</TableCell>
								</TableRow>
							))}
							{list.length === 0 && (
								<TableRow>
									<TableCell
										colSpan={8}
										className="py-12 text-center text-muted-foreground"
									>
										No players match.
									</TableCell>
								</TableRow>
							)}
						</TableBody>
					</Table>
				</CardContent>
			</Card>

			{/* Bulk bar */}
			{checked.size > 0 && (
				<div className="fixed bottom-5 left-1/2 z-40 flex -translate-x-1/2 flex-wrap items-center gap-2 rounded-xl border bg-card px-4 py-3 shadow-card">
					<span className="tnum mr-1 text-sm font-medium">
						{checked.size} selected
					</span>
					<Button
						size="sm"
						variant="secondary"
						onClick={() =>
							bulkMutate(
								"/api/players/grant-all-skins",
								{},
								`Granted all skins to ${checked.size} player(s)`,
							)
						}
					>
						All skins
					</Button>
					<Button
						size="sm"
						variant="secondary"
						onClick={() =>
							bulkMutate(
								"/api/players/grant-all-legendary-rift-crystals",
								{ wipeTestEquip: false },
								`Granted legendary crystals to ${checked.size} player(s)`,
							)
						}
					>
						Legendary crystals
					</Button>
					<Button
						size="sm"
						variant="secondary"
						onClick={() =>
							bulkMutate(
								"/api/players/grant-all-premium-altars",
								{},
								`Granted premium altars to ${checked.size} player(s)`,
							)
						}
					>
						Premium altars
					</Button>
					<Button
						size="sm"
						variant="secondary"
						onClick={() =>
							bulkMutate(
								"/api/players/toggle-infinity-rift",
								{ enable: true },
								`Enabled Infinity Rift for ${checked.size} player(s)`,
							)
						}
					>
						Infinity rift on
					</Button>
					<Button
						size="sm"
						variant="ghost"
						onClick={() => setChecked(new Set())}
					>
						<X className="h-4 w-4" /> Clear
					</Button>
				</div>
			)}

			{/* Create dialog */}
			<Dialog open={showCreate} onClose={() => setShowCreate(false)}>
				<DialogHeader onClose={() => setShowCreate(false)}>
					<DialogTitle>Create player</DialogTitle>
					<p className="mt-1 text-sm text-muted-foreground">
						Built by the game server (default save + content-version expansion).
					</p>
				</DialogHeader>
				<DialogContent className="space-y-3">
					<div className="space-y-1">
						<label className="text-xs text-muted-foreground" htmlFor="new-name">
							Name
						</label>
						<Input
							id="new-name"
							value={newName}
							onChange={(e) => setNewName(e.target.value)}
							placeholder="e.g. Newbie"
						/>
					</div>
					<div className="space-y-1">
						<label className="text-xs text-muted-foreground" htmlFor="new-uid">
							UID (optional, auto-generated)
						</label>
						<Input
							id="new-uid"
							value={newUid}
							onChange={(e) => setNewUid(e.target.value)}
							placeholder="player-xxxx"
							className="font-mono"
						/>
					</div>
				</DialogContent>
				<DialogFooter>
					<Button variant="ghost" onClick={() => setShowCreate(false)}>
						Cancel
					</Button>
					<Button onClick={handleCreate} disabled={!newName.trim()}>
						Create
					</Button>
				</DialogFooter>
			</Dialog>

			{drawerPid && (
				<PlayerDrawer
					pid={drawerPid}
					onClose={() => setDrawerPid(null)}
					onMutate={mutatePlayers}
				/>
			)}
		</div>
	);
}

function PlayerDrawer({
	pid,
	onClose,
	onMutate,
}: {
	pid: string;
	onClose: () => void;
	onMutate: () => void;
}) {
	const { data: detail } = usePlayer(pid);
	const sum = (detail as PlayerDetailResponse | undefined)?.summary;
	const [showRaw, setShowRaw] = useState(false);

	useEffect(() => {
		const onKey = (e: KeyboardEvent) => {
			if (e.key === "Escape") onClose();
		};
		window.addEventListener("keydown", onKey);
		return () => window.removeEventListener("keydown", onKey);
	}, [onClose]);

	const handleActivate = async () => {
		await runMutation(
			`/api/players/${encodeURIComponent(pid)}/activate`,
			{ method: "POST" },
			`Activated ${sum?.name ?? pid}`,
		);
		onMutate();
	};
	const handleClone = async () => {
		await runMutation(
			`/api/players/${encodeURIComponent(pid)}/clone`,
			{ method: "POST" },
			"Player cloned",
		);
		onMutate();
	};
	const handleDelete = async () => {
		if (!window.confirm(`Delete player ${pid}? This is irreversible.`)) return;
		await runMutation(
			`/api/players/${encodeURIComponent(pid)}`,
			{ method: "DELETE" },
			"Player deleted",
		);
		onClose();
		onMutate();
	};

	return (
		<div className="fixed inset-0 z-50">
			<button
				type="button"
				aria-label="Close drawer"
				onClick={onClose}
				className="absolute inset-0 cursor-default bg-black/40"
			/>
			<aside className="absolute bottom-0 right-0 top-0 w-[min(95vw,44rem)] overflow-y-auto border-l bg-card shadow-card">
				<div className="sticky top-0 z-10 flex items-start justify-between gap-3 border-b bg-card px-5 py-4">
					<div className="min-w-0">
						<h2 className="flex items-center gap-2 text-lg font-semibold tracking-tight">
							<span className="truncate">{sum?.name ?? pid}</span>
							{sum?.active && <Badge variant="success">in session</Badge>}
						</h2>
						<p className="truncate font-mono text-xs text-muted-foreground">
							{pid} · uid {sum?.uid} · castle “{sum?.castleName || "-"}”
						</p>
					</div>
					<Button
						variant="ghost"
						size="icon"
						onClick={onClose}
						aria-label="Close"
					>
						<X className="h-4 w-4" />
					</Button>
				</div>

				<div className="space-y-5 p-5">
					<WalletEditor pid={pid} sum={sum} onMutate={onMutate} />

					{/* Quick actions */}
					<div className="flex flex-wrap gap-2">
						{!sum?.active && (
							<Button variant="outline" size="sm" onClick={handleActivate}>
								<UserCheck className="h-4 w-4" /> Set active session
							</Button>
						)}
						<Button variant="outline" size="sm" onClick={handleClone}>
							<Copy className="h-4 w-4" /> Clone
						</Button>
						<Button variant="destructive" size="sm" onClick={handleDelete}>
							<Trash2 className="h-4 w-4" /> Delete
						</Button>
					</div>

					<MacroQuickActions pid={pid} onMutate={onMutate} />

					<RiftEnhanceRates pid={pid} />

					<PortalAccess pid={pid} />

					{/* Raw JSON editor */}
					<div className="rounded-lg border">
						<button
							type="button"
							onClick={() => setShowRaw((v) => !v)}
							className="flex w-full items-center justify-between px-4 py-3 text-sm font-medium hover:bg-surface-2"
						>
							Raw state (JSON editor)
							{showRaw ? (
								<ChevronDown className="h-4 w-4 text-muted-foreground" />
							) : (
								<ChevronRight className="h-4 w-4 text-muted-foreground" />
							)}
						</button>
						{showRaw && <RawEditor pid={pid} onMutate={onMutate} />}
					</div>
				</div>
			</aside>
		</div>
	);
}

function WalletEditor({
	pid,
	sum,
	onMutate,
}: {
	pid: string;
	sum?: PlayerSummary;
	onMutate: () => void;
}) {
	const [edits, setEdits] = useState<Record<string, string>>({});
	const hasSummary = Boolean(sum);
	const editableFingerprint = JSON.stringify(
		(() => {
			const next: Record<string, string> = {};
			for (const key of Object.keys(EDITABLE_FIELDS)) {
				next[key] =
					sum?.[key] !== undefined && sum[key] !== null ? String(sum[key]) : "";
			}
			return next;
		})(),
	);

	useEffect(() => {
		if (hasSummary) {
			// A selected save is an external query result; reset the edit draft only when it changes.
			// eslint-disable-next-line react-hooks/set-state-in-effect
			setEdits(JSON.parse(editableFingerprint) as Record<string, string>);
		}
	}, [pid, hasSummary, editableFingerprint]);

	const saveEdits = async () => {
		const patch: Record<string, string | number> = {};
		for (const [k, v] of Object.entries(edits)) {
			const spec = EDITABLE_FIELDS[k];
			if (spec?.type === "number") {
				const n = Number(v);
				if (!Number.isNaN(n) && n !== sum?.[k]) patch[k] = n;
			} else if (v !== sum?.[k]) {
				patch[k] = v;
			}
		}
		if (!Object.keys(patch).length) return;
		await runMutation(
			`/api/player/${encodeURIComponent(pid)}`,
			{ method: "PATCH", body: JSON.stringify(patch) },
			"Save updated",
		);
		onMutate();
	};

	if (!sum)
		return (
			<Card>
				<CardContent className="py-8 text-center text-sm text-muted-foreground">
					Loading player…
				</CardContent>
			</Card>
		);

	return (
		<Card>
			<CardHeader>
				<div>
					<CardTitle>Fields</CardTitle>
					<CardDescription>
						Wallet and progress. Only changed values are sent.
					</CardDescription>
				</div>
				<Button size="sm" onClick={saveEdits}>
					<Save className="h-4 w-4" /> Save
				</Button>
			</CardHeader>
			<CardContent>
				<div className="grid grid-cols-2 gap-3 md:grid-cols-3">
					{Object.entries(EDITABLE_FIELDS).map(([k, spec]) => (
						<div key={k} className="space-y-1">
							<label
								htmlFor={`field-${k}`}
								className="text-xs text-muted-foreground"
							>
								{spec.label}
							</label>
							<Input
								id={`field-${k}`}
								type={spec.type || "text"}
								value={edits[k] ?? ""}
								onChange={(e) =>
									setEdits((prev) => ({ ...prev, [k]: e.target.value }))
								}
							/>
						</div>
					))}
				</div>
			</CardContent>
		</Card>
	);
}

const MACROS: { id: string; label: string; group: string }[] = [
	{ id: "max_resources", label: "Max Resources (290909)", group: "Resources" },
	{ id: "max_wealth", label: "Max Wealth + tokens", group: "Resources" },
	{ id: "max_inventory", label: "Max inventory", group: "Resources" },
	{ id: "hero_basic", label: "Heroes lv20", group: "Heroes" },
	{ id: "hero_advanced", label: "Heroes lv30 + souls", group: "Heroes" },
	{ id: "hero_max", label: "Max heroes", group: "Heroes" },
	{ id: "grant_all_skins", label: "All skins", group: "Heroes" },
	{ id: "legacy_basic", label: "Legacies 0*", group: "Legacies" },
	{ id: "legacy_advanced", label: "Legacies 10*", group: "Legacies" },
	{ id: "legacy_max", label: "Max legacies", group: "Legacies" },
	{ id: "accessory_admin", label: "Admin accessories", group: "Legacies" },
	{ id: "grant_premium_altars", label: "Premium altars", group: "Rift" },
	{ id: "rift_legendary_all", label: "Legendary crystals", group: "Rift" },
	{ id: "toggle_infinity_rift", label: "Toggle infinity rift", group: "Rift" },
];

function MacroQuickActions({
	pid,
	onMutate,
}: {
	pid: string;
	onMutate: () => void;
}) {
	const [busy, setBusy] = useState<string | null>(null);
	const groups = [...new Set(MACROS.map((m) => m.group))];

	const handleMacro = async (macroId: string) => {
		if (
			!window.confirm(
				`Apply macro '${macroId}'? This will overwrite relevant fields.`,
			)
		)
			return;
		setBusy(macroId);
		try {
			await runMutation(
				`/api/player/${encodeURIComponent(pid)}/macro`,
				{ method: "POST", body: JSON.stringify({ macro: macroId }) },
				"Macro applied",
			);
			onMutate();
		} finally {
			setBusy(null);
		}
	};

	return (
		<Card>
			<CardHeader>
				<div>
					<CardTitle className="flex items-center gap-2">
						<Zap className="h-4 w-4" /> Macros
					</CardTitle>
					<CardDescription>
						Bundles applied to this player only.
					</CardDescription>
				</div>
			</CardHeader>
			<CardContent className="space-y-3">
				{groups.map((g) => (
					<div key={g} className="flex flex-wrap items-center gap-2">
						<span className="w-20 shrink-0 text-xs font-medium uppercase tracking-wide text-muted-foreground">
							{g}
						</span>
						{MACROS.filter((m) => m.group === g).map((m) => (
							<Button
								key={m.id}
								size="sm"
								variant="secondary"
								disabled={busy === m.id}
								onClick={() => handleMacro(m.id)}
							>
								{busy === m.id ? "…" : m.label}
							</Button>
						))}
					</div>
				))}
			</CardContent>
		</Card>
	);
}

function RawEditor({ pid, onMutate }: { pid: string; onMutate: () => void }) {
	const { data: raw } = usePlayerRaw(pid);
	const [rawDraft, setRawDraft] = useState("");
	const [rawError, setRawError] = useState<string | null>(null);

	useEffect(() => {
		if (raw) {
			// A selected save is an external query result; initialize the raw-state editor from it.
			// eslint-disable-next-line react-hooks/set-state-in-effect
			setRawDraft(JSON.stringify(raw, null, 2));
		}
	}, [raw]);

	const saveRaw = async () => {
		setRawError(null);
		let parsed: unknown;
		try {
			parsed = JSON.parse(rawDraft);
		} catch (error: unknown) {
			setRawError(
				"Invalid JSON: " +
					(error instanceof Error ? error.message : "unknown parse error"),
			);
			return;
		}
		await runMutation(
			`/api/player/${encodeURIComponent(pid)}/raw`,
			{ method: "PUT", body: JSON.stringify(parsed) },
			"Raw state replaced",
		);
		onMutate();
	};

	return (
		<div className="border-t px-4 py-4">
			<p className="mb-2 text-xs text-muted-foreground">
				Full save as the game server reads it. uid is forced back to the row key
				on save.
			</p>
			<textarea
				value={rawDraft}
				onChange={(e) => setRawDraft(e.target.value)}
				spellCheck={false}
				className="h-96 w-full rounded-md border border-input bg-surface-2 p-3 font-mono text-xs focus:outline-none focus:ring-2 focus:ring-ring"
			/>
			{rawError && <p className="mt-2 text-sm text-destructive">{rawError}</p>}
			<div className="mt-3 flex gap-2">
				<Button onClick={saveRaw}>
					<Save className="h-4 w-4" /> Replace raw state
				</Button>
				<Button
					variant="outline"
					onClick={() => setRawDraft(JSON.stringify(raw, null, 2))}
				>
					<RefreshCw className="h-4 w-4" /> Reload
				</Button>
			</div>
		</div>
	);
}

type PortalAccount = {
	login_id: string;
	username: string | null;
	created: number | null;
	last_login: number | null;
	must_change_password: boolean;
};

function PortalAccess({ pid }: { pid: string }) {
	const { data, isLoading } = useQuery({
		queryKey: ["/api/player/portal-access", pid],
		queryFn: () =>
			fetcher(`/api/player/${encodeURIComponent(pid)}/portal-access`),
		refetchOnWindowFocus: false,
	});
	const [loginId, setLoginId] = useState("");
	const [username, setUsername] = useState("");
	const [password, setPassword] = useState("");

	const accounts: PortalAccount[] = data?.accounts ?? [];
	const guests = accounts.filter((account) =>
		account.login_id.startsWith("Guest_"),
	);
	// Derive the effective selection instead of syncing state on prop changes:
	// keep the picked guest when it still exists, else the first guest.
	const activeLogin = guests.some((g) => g.login_id === loginId)
		? loginId
		: (guests[0]?.login_id ?? "");

	const issue = async () => {
		await runMutation(
			`/api/player/${encodeURIComponent(pid)}/portal-access`,
			{
				method: "POST",
				body: JSON.stringify({ loginId: activeLogin, username, password }),
			},
			"Guest portal password issued",
		);
		setPassword("");
	};
	return (
		<Card>
			<CardHeader>
				<div>
					<CardTitle>Player Portal access</CardTitle>
					<CardDescription>
						Google accounts use Google sign-in. For a Guest account, issue a
						temporary password only after verifying its owner.
					</CardDescription>
				</div>
			</CardHeader>
			<CardContent className="space-y-4">
				{isLoading ? (
					<p className="text-sm text-muted-foreground">
						Loading linked game accounts…
					</p>
				) : (
					<>
						{accounts.length === 0 ? (
							<p className="text-sm text-muted-foreground">
								This save has no game login yet. The player must enter the game
								before portal access can be granted.
							</p>
						) : (
							<ul className="space-y-2 text-sm">
								{accounts.map((account) => (
									<li key={account.login_id} className="rounded-md border p-3">
										<div className="font-mono break-all">
											{account.login_id}
										</div>
										<div className="mt-1 text-muted-foreground">
											{account.login_id.startsWith("google_")
												? "Google sign-in"
												: account.username
													? `Guest portal name: ${account.username}${account.must_change_password ? " · password change required" : ""}`
													: "Guest account - no portal password yet"}
										</div>
									</li>
								))}
							</ul>
						)}
						{guests.length > 0 && (
							<div className="grid gap-3 rounded-md border p-3 sm:grid-cols-3 sm:items-end">
								<div className="space-y-1">
									<label
										htmlFor="portal-guest"
										className="text-xs text-muted-foreground"
									>
										Guest account
									</label>
									<Select
										id="portal-guest"
										value={activeLogin}
										onChange={(event) => setLoginId(event.target.value)}
									>
										{guests.map((account) => (
											<option key={account.login_id} value={account.login_id}>
												{account.login_id}
											</option>
										))}
									</Select>
								</div>
								<div className="space-y-1">
									<label
										htmlFor="portal-username"
										className="text-xs text-muted-foreground"
									>
										Portal username
									</label>
									<Input
										id="portal-username"
										value={username}
										onChange={(event) => setUsername(event.target.value)}
										placeholder="guest_name"
									/>
								</div>
								<div className="space-y-1">
									<label
										htmlFor="portal-password"
										className="text-xs text-muted-foreground"
									>
										Temporary password
									</label>
									<Input
										id="portal-password"
										value={password}
										onChange={(event) => setPassword(event.target.value)}
										type="password"
										minLength={8}
										placeholder="At least 8 characters"
									/>
								</div>
								<Button
									className="sm:col-span-3 sm:w-fit"
									disabled={!activeLogin || !username || password.length < 8}
									onClick={issue}
								>
									Issue Guest access
								</Button>
							</div>
						)}
					</>
				)}
			</CardContent>
		</Card>
	);
}

type RiftRateFields = { success: string; fail: string; down: string; broken: string };
const RIFT_RATE_KEYS = ["success", "fail", "down", "broken"] as const;

function RiftEnhanceRates({ pid }: { pid: string }) {
	const { data, isLoading } = useQuery({
		queryKey: ["/api/player/rift-upgrade-rates", pid],
		queryFn: () =>
			fetcher(`/api/player/${encodeURIComponent(pid)}/rift-upgrade-rates`),
		refetchOnWindowFocus: false,
	});
	const master: Record<string, number> | null = data?.rates ?? null;
	const fingerprint = JSON.stringify(master);
	const [enabled, setEnabled] = useState(false);
	const [fields, setFields] = useState<RiftRateFields>({
		success: "100",
		fail: "0",
		down: "0",
		broken: "0",
	});

	useEffect(() => {
		// A loaded save is an external query result; reset the draft only when the
		// stored override (or the selected account) changes.
		// eslint-disable-next-line react-hooks/set-state-in-effect
		setEnabled(Boolean(master));
		if (master) {
			setFields({
				success: String(master.success ?? 0),
				fail: String(master.fail ?? 0),
				down: String(master.down ?? 0),
				broken: String(master.broken ?? 0),
			});
		} else {
			setFields({ success: "100", fail: "0", down: "0", broken: "0" });
		}
		// `master` is re-derived from `fingerprint`; depending on the object itself
		// would re-run the effect on every query refetch.
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, [pid, fingerprint]);

	const total = RIFT_RATE_KEYS.reduce((sum, k) => sum + (Number(fields[k]) || 0), 0);
	const invalid =
		enabled &&
		(total <= 0 ||
			RIFT_RATE_KEYS.some((k) => {
				const n = Number(fields[k]);
				return fields[k] === "" || Number.isNaN(n) || n < 0 || n > 100;
			}));

	const save = async () => {
		const body = enabled
			? {
					success: Number(fields.success),
					fail: Number(fields.fail),
					down: Number(fields.down),
					broken: Number(fields.broken),
				}
			: { clear: true };
		await runMutation(
			`/api/player/${encodeURIComponent(pid)}/rift-upgrade-rates`,
			{ method: "POST", body: JSON.stringify(body) },
			enabled ? "Enhance rates updated" : "Enhance rates reset to default",
		);
	};

	return (
		<Card>
			<CardHeader>
				<div>
					<CardTitle>Rift Enhance rates</CardTitle>
					<CardDescription>
						Override the success / fail / down / broken outcome for this
						account&apos;s rift-weapon (đồ khe) enhancement. Values are relative
						weights; leave off to use per-level master data.
					</CardDescription>
				</div>
			</CardHeader>
			<CardContent className="space-y-4">
				{isLoading ? (
					<p className="text-sm text-muted-foreground">Loading…</p>
				) : (
					<>
						<label className="flex items-center gap-2 text-sm">
							<input
								type="checkbox"
								checked={enabled}
								onChange={(e) => setEnabled(e.target.checked)}
								className="h-4 w-4 accent-[var(--primary)]"
							/>
							Use custom Enhance rates for this account
						</label>
						{enabled && (
							<>
								<div className="grid grid-cols-2 gap-3 md:grid-cols-4">
									{RIFT_RATE_KEYS.map((k) => (
										<div key={k} className="space-y-1">
											<label
												htmlFor={`rift-${k}`}
												className="text-xs capitalize text-muted-foreground"
											>
												{k} %
											</label>
											<Input
												id={`rift-${k}`}
												type="number"
												min={0}
												max={100}
												value={fields[k]}
												onChange={(e) =>
													setFields((prev) => ({ ...prev, [k]: e.target.value }))
												}
											/>
										</div>
									))}
								</div>
								<p className="text-xs text-muted-foreground">
									Total {total}%. Weights are normalised to 100% at roll time
									{total > 0 && Math.abs(total - 100) > 0.001
										? ` — effective success ≈ ${(Number(fields.success) * 100 / total).toFixed(1)}%`
										: ""}
									.
								</p>
							</>
						)}
						<Button size="sm" disabled={invalid} onClick={save}>
							<Save className="h-4 w-4" />
							{enabled ? "Save rates" : "Reset to default"}
						</Button>
					</>
				)}
			</CardContent>
		</Card>
	);
}
