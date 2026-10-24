"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
	useStatus,
	usePlayers,
	useServerSection,
	useRealtimeStats,
	useAudit,
	useRaidAdmin,
	fetcher,
} from "@/lib/api";
import {
	Card,
	CardContent,
	CardHeader,
	CardTitle,
	CardDescription,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
	type LucideIcon,
	Users,
	Activity,
	Coins,
	Gem,
	Heart,
	ScrollText,
	Cpu,
	MemoryStick,
	Swords,
	History,
	ChevronRight,
} from "lucide-react";
import {
	LineChart,
	Line,
	XAxis,
	YAxis,
	Tooltip,
	ResponsiveContainer,
	CartesianGrid,
	Legend,
} from "recharts";

type PlayerSummary = {
	id: string;
	name: string;
	active?: boolean;
	level?: number;
	gold?: number;
	cash?: number;
	heart?: number;
	counts?: { posts?: number; cards?: number; items?: number };
};
type ChartPoint = { time: string; [k: string]: string | number };
type RaidRow = {
	pid: string;
	clanId?: string;
	clanName?: string;
	boss?: string;
	stage?: number;
	round?: number;
	killCount?: number;
	score?: number;
	remainHp?: number;
	remainBattleCount?: number;
};

const HISTORY_POINTS = 60;

// Polling samples arrive from react-query; the effects below append each one
// to a capped rolling window (newest last) so the charts hold a 60-point view
// without any server-side history.
function pushPoint(prev: ChartPoint[], p: ChartPoint): ChartPoint[] {
	return [...prev.slice(-(HISTORY_POINTS - 1)), p];
}

function nowStr() {
	const d = new Date();
	return `${d.getHours().toString().padStart(2, "0")}:${d.getMinutes().toString().padStart(2, "0")}:${d.getSeconds().toString().padStart(2, "0")}`;
}

function fmt(n: number | undefined | null) {
	if (n === undefined || n === null) return "-";
	return n.toLocaleString();
}

function Kpi({
	label,
	value,
	sub,
	icon: Icon,
	accent,
}: {
	label: string;
	value: string;
	sub?: string;
	icon: LucideIcon;
	accent?: string;
}) {
	return (
		<Card>
			<CardHeader>
				<CardTitle className="flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
					<Icon className={`h-4 w-4 ${accent ?? "text-muted-foreground"}`} />
					{label}
				</CardTitle>
			</CardHeader>
			<CardContent>
				<div className="tnum text-2xl font-semibold tracking-tight">
					{value}
				</div>
				{sub && (
					<div className="mt-0.5 text-xs text-muted-foreground">{sub}</div>
				)}
			</CardContent>
		</Card>
	);
}

const CHART_TICK = {
	fontSize: 11,
	tickLine: false,
	axisLine: false,
	stroke: "var(--muted-foreground)",
} as const;

export default function OverviewPage() {
	const { data: status, error } = useStatus();
	const { data: players } = usePlayers();
	const { data: sys } = useServerSection("system", 2000);
	const { data: realtime } = useRealtimeStats();
	const { data: audit } = useAudit(5);
	const { data: raid } = useRaidAdmin();
	const { data: pending } = useQuery({
		queryKey: ["/api/requests", "pending"],
		queryFn: () => fetcher("/api/requests?status=pending"),
		refetchInterval: 15000,
	});

	const [ccuHistory, setCcuHistory] = useState<ChartPoint[]>([]);
	const [sysHistory, setSysHistory] = useState<ChartPoint[]>([]);

	useEffect(() => {
		if (!realtime) return;
		// The query result is an external polling source; appending here is the
		// intended reactive pattern.
		// eslint-disable-next-line react-hooks/set-state-in-effect
		setCcuHistory((prev) =>
			pushPoint(prev, { time: nowStr(), ccu: realtime.ccu }),
		);
	}, [realtime]);

	useEffect(() => {
		if (!sys?.ok || !sys.data) return;
		// eslint-disable-next-line react-hooks/set-state-in-effect
		setSysHistory((prev) =>
			pushPoint(prev, {
				time: nowStr(),
				cpu: sys.data.cpu.load1,
				ram: sys.data.mem.percent,
			}),
		);
	}, [sys]);

	if (!status && !error)
		return <div className="p-8 text-muted-foreground">Loading status...</div>;
	if (error)
		return (
			<div className="p-8 text-destructive">Failed to load system status.</div>
		);

	const list = (Array.isArray(players) ? players : []) as PlayerSummary[];
	const totals = list.reduce(
		(acc, p) => ({
			gold: acc.gold + (p.gold || 0),
			cash: acc.cash + (p.cash || 0),
			heart: acc.heart + (p.heart || 0),
		}),
		{ gold: 0, cash: 0, heart: 0 },
	);

	const raids = (raid?.raids ?? []) as RaidRow[];
	const activeRaids = raids.filter((r) => r.remainBattleCount);
	const pendingCount = pending?.entries?.length ?? 0;
	const sysData = sys?.ok ? sys.data : null;

	return (
		<div className="space-y-6">
			<div>
				<h1 className="text-2xl font-semibold tracking-tight">Overview</h1>
				<p className="text-sm text-muted-foreground">
					Live server health, economy and pending work.
				</p>
			</div>

			{/* KPI row */}
			<div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
				<Kpi
					label="Players"
					value={fmt(status.players)}
					sub={`${fmt(realtime?.active_24h)} active 24h`}
					icon={Users}
					accent="text-blue-600 dark:text-blue-400"
				/>
				<Kpi
					label="CCU"
					value={fmt(realtime?.ccu)}
					sub="last 15s"
					icon={Activity}
					accent="text-emerald-600 dark:text-emerald-400"
				/>
				<Kpi
					label="Gold"
					value={fmt(realtime?.total_gold ?? totals.gold)}
					sub="all accounts"
					icon={Coins}
					accent="text-amber-600 dark:text-amber-400"
				/>
				<Kpi
					label="Cash"
					value={fmt(realtime?.total_cash ?? totals.cash)}
					sub="all accounts"
					icon={Gem}
					accent="text-violet-600 dark:text-violet-400"
				/>
				<Kpi
					label="Heart"
					value={fmt(totals.heart)}
					sub="all accounts"
					icon={Heart}
					accent="text-rose-600 dark:text-rose-400"
				/>
				<Link href="/requests" className="block">
					<Card className="h-full transition-colors hover:bg-surface-2">
						<CardHeader>
							<CardTitle className="flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
								<ScrollText className="h-4 w-4 text-orange-600 dark:text-orange-400" />
								Requests
							</CardTitle>
						</CardHeader>
						<CardContent>
							<div className="tnum flex items-center gap-2 text-2xl font-semibold tracking-tight">
								{fmt(pendingCount)}
								{pendingCount > 0 && <Badge variant="warn">pending</Badge>}
							</div>
							<div className="mt-0.5 text-xs text-muted-foreground">
								player grant queue
							</div>
						</CardContent>
					</Card>
				</Link>
			</div>

			{/* Charts */}
			<div className="grid gap-4 lg:grid-cols-2">
				<Card>
					<CardHeader>
						<div>
							<CardTitle className="flex items-center gap-2">
								Realtime CCU
							</CardTitle>
							<CardDescription>
								Concurrent users, 2s samples (60-point window).
							</CardDescription>
						</div>
					</CardHeader>
					<CardContent className="h-64">
						<ResponsiveContainer width="100%" height="100%">
							<LineChart
								data={ccuHistory}
								margin={{ top: 5, right: 10, left: -25, bottom: 0 }}
							>
								<CartesianGrid
									strokeDasharray="3 3"
									vertical={false}
									stroke="var(--border)"
								/>
								<XAxis dataKey="time" tick={CHART_TICK} minTickGap={40} />
								<YAxis allowDecimals={false} tick={CHART_TICK} width={40} />
								<Tooltip
									contentStyle={{
										backgroundColor: "var(--card)",
										borderColor: "var(--border)",
										borderRadius: "8px",
										fontSize: 12,
									}}
								/>
								<Line
									type="monotone"
									dataKey="ccu"
									name="CCU"
									stroke="var(--color-success)"
									strokeWidth={2}
									dot={false}
								/>
							</LineChart>
						</ResponsiveContainer>
					</CardContent>
				</Card>

				<Card>
					<CardHeader>
						<div>
							<CardTitle className="flex items-center gap-2">
								Host CPU / RAM
							</CardTitle>
							<CardDescription>
								Load 1m &amp; memory utilization (%).
							</CardDescription>
						</div>
						{sysData && (
							<span className="tnum flex items-center gap-3 text-xs text-muted-foreground">
								<span className="flex items-center gap-1">
									<Cpu size={12} />
									{sysData.cpu.load1}
								</span>
								<span className="flex items-center gap-1">
									<MemoryStick size={12} />
									{sysData.mem.percent}%
								</span>
							</span>
						)}
					</CardHeader>
					<CardContent className="h-64">
						<ResponsiveContainer width="100%" height="100%">
							<LineChart
								data={sysHistory}
								margin={{ top: 5, right: 10, left: -25, bottom: 0 }}
							>
								<CartesianGrid
									strokeDasharray="3 3"
									vertical={false}
									stroke="var(--border)"
								/>
								<XAxis dataKey="time" tick={CHART_TICK} minTickGap={40} />
								<YAxis tick={CHART_TICK} width={40} />
								<Tooltip
									contentStyle={{
										backgroundColor: "var(--card)",
										borderColor: "var(--border)",
										borderRadius: "8px",
										fontSize: 12,
									}}
								/>
								<Legend wrapperStyle={{ fontSize: 12 }} />
								<Line
									type="monotone"
									dataKey="cpu"
									name="CPU load"
									stroke="var(--chart-line)"
									strokeWidth={2}
									dot={false}
								/>
								<Line
									type="monotone"
									dataKey="ram"
									name="RAM %"
									stroke="var(--warning)"
									strokeWidth={2}
									dot={false}
								/>
							</LineChart>
						</ResponsiveContainer>
					</CardContent>
				</Card>
			</div>

			{/* Side panels: raid + recent actions */}
			<div className="grid gap-4 lg:grid-cols-2">
				<Card>
					<CardHeader>
						<div>
							<CardTitle className="flex items-center gap-2">
								<Swords className="h-4 w-4" /> Clan Raid
							</CardTitle>
							<CardDescription>Latest boss progress per clan.</CardDescription>
						</div>
						<Link
							href="/raid"
							className="flex items-center gap-0.5 text-xs font-medium text-muted-foreground hover:text-foreground"
						>
							Manage <ChevronRight size={12} />
						</Link>
					</CardHeader>
					<CardContent>
						{raids.length === 0 && (
							<p className="text-sm text-muted-foreground">
								No clans formed yet.
							</p>
						)}
						<ul className="divide-y divide-border">
							{raids.slice(0, 5).map((r) => (
								<li
									key={r.pid}
									className="flex items-center justify-between gap-3 py-2.5 text-sm"
								>
									<div className="min-w-0">
										<p className="truncate font-medium">
											{r.clanName || r.clanId}
										</p>
										<p className="tnum truncate text-xs text-muted-foreground">
											round {r.round ?? "-"} · stage {r.stage ?? "-"} · kills{" "}
											{fmt(r.killCount)} · score {fmt(r.score)}
										</p>
									</div>
									{r.remainHp != null && (
										<Badge
											variant={r.remainHp <= 0 ? "success" : "neutral"}
											className="tnum shrink-0"
										>
											HP {fmt(r.remainHp)}
										</Badge>
									)}
								</li>
							))}
						</ul>
						{activeRaids.length > 0 && (
							<p className="tnum mt-2 text-xs text-muted-foreground">
								{activeRaids.length} battle(s) in progress
							</p>
						)}
					</CardContent>
				</Card>

				<Card>
					<CardHeader>
						<div>
							<CardTitle className="flex items-center gap-2">
								<History className="h-4 w-4" /> Recent admin actions
							</CardTitle>
							<CardDescription>
								Newest entries in the audit trail.
							</CardDescription>
						</div>
						<Link
							href="/audit"
							className="flex items-center gap-0.5 text-xs font-medium text-muted-foreground hover:text-foreground"
						>
							Full log <ChevronRight size={12} />
						</Link>
					</CardHeader>
					<CardContent>
						{(audit?.entries ?? []).length === 0 && (
							<p className="text-sm text-muted-foreground">
								No admin actions recorded yet.
							</p>
						)}
						<ul className="divide-y divide-border">
							{(audit?.entries ?? []).map(
								(e: {
									id: number;
									ts: number;
									username: string;
									action: string;
									target?: string | null;
								}) => (
									<li
										key={e.id}
										className="flex items-center justify-between gap-3 py-2 text-sm"
									>
										<div className="min-w-0">
											<span className="font-medium">{e.action}</span>
											{e.target && (
												<span className="ml-2 font-mono text-xs text-muted-foreground">
													{e.target}
												</span>
											)}
										</div>
										<span className="tnum shrink-0 text-xs text-muted-foreground">
											{new Date(e.ts * 1000).toLocaleTimeString()} ·{" "}
											{e.username}
										</span>
									</li>
								),
							)}
						</ul>
					</CardContent>
				</Card>
			</div>

			{/* Server facts */}
			<Card>
				<CardHeader>
					<div>
						<CardTitle>Server</CardTitle>
						<CardDescription>Configuration and host facts.</CardDescription>
					</div>
					<Link
						href="/server"
						className="flex items-center gap-0.5 text-xs font-medium text-muted-foreground hover:text-foreground"
					>
						Diagnostics <ChevronRight size={12} />
					</Link>
				</CardHeader>
				<CardContent>
					<dl className="grid grid-cols-2 gap-x-6 gap-y-3 text-sm md:grid-cols-4">
						<div>
							<dt className="text-xs uppercase tracking-wide text-muted-foreground">
								Version
							</dt>
							<dd className="tnum mt-0.5 font-medium">{status.version}</dd>
						</div>
						<div>
							<dt className="text-xs uppercase tracking-wide text-muted-foreground">
								Patch folder
							</dt>
							<dd className="mt-0.5 font-medium">{status.patchFolder}</dd>
						</div>
						<div>
							<dt className="text-xs uppercase tracking-wide text-muted-foreground">
								Multiplayer
							</dt>
							<dd className="mt-0.5">
								<Badge variant={status.multiplayer ? "success" : "neutral"}>
									{status.multiplayer ? "Enabled" : "Disabled"}
								</Badge>
							</dd>
						</div>
						<div>
							<dt className="text-xs uppercase tracking-wide text-muted-foreground">
								Uptime
							</dt>
							<dd className="mt-0.5 font-medium">
								{sysData?.uptimeStr ?? "-"}
							</dd>
						</div>
					</dl>
				</CardContent>
			</Card>
		</div>
	);
}
