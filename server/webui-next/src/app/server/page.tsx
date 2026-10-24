"use client";

import { useEffect, useMemo, useRef, type ReactNode, useState } from "react";
import { useServerLogs, useServerSection } from "@/lib/api";
import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs } from "@/components/ui/tabs";
import {
	RefreshCw,
	Server,
	Timer,
	Users,
	Route,
	Database,
	ScrollText,
	MemoryStick,
	Cpu,
	HardDrive,
	AlertTriangle,
	CheckCircle2,
	Pause,
	Play,
} from "lucide-react";

const SECTIONS = [
	{ id: "system", label: "System" },
	{ id: "logs", label: "Logs" },
	{ id: "routes", label: "Routes" },
	{ id: "cdn", label: "CDN" },
	{ id: "config", label: "Config" },
	{ id: "info", label: "Info" },
];

type IconComponent = (props: { className?: string }) => ReactNode;
type JsonValue = string | number | boolean | null | JsonObject | JsonValue[];
type JsonObject = { [key: string]: JsonValue | undefined };
type RouteRow = { path: string; model?: string; overridden?: boolean };
type CdnFile = { name: string; size: number };

function MiniStat({
	icon: Icon,
	label,
	value,
	color,
}: {
	icon: IconComponent;
	label: string;
	value: ReactNode;
	color: string;
}) {
	return (
		<div className="flex items-center gap-3 rounded-xl border border-border bg-card px-3 py-2 shadow-card">
			<Icon className={`h-4 w-4 ${color}`} />
			<div>
				<div className="text-[10px] uppercase tracking-wide text-muted-foreground">
					{label}
				</div>
				<div className="text-sm font-semibold font-mono tnum">
					{value ?? "-"}
				</div>
			</div>
		</div>
	);
}

function JsonView({ data }: { data: JsonValue }) {
	return (
		<pre className="max-h-[60vh] overflow-auto rounded-lg bg-muted/40 p-4 font-mono text-xs leading-relaxed">
			{JSON.stringify(data, null, 2)}
		</pre>
	);
}

// Game-server log file tail (dashboard GET /api/server/logs), 3s auto-refresh
// with a pause toggle. Kept dark: a log viewer reads better as a terminal.
function LogsPanel() {
	const [paused, setPaused] = useState(false);
	const [lines, setLinesCount] = useState(200);
	const { data, error, isLoading } = useServerLogs(lines, 3000, paused);
	const boxRef = useRef<HTMLDivElement>(null);
	// Lines can repeat within one tail, so decorate keys with an occurrence count.
	const logLines = useMemo(() => {
		const raw = (data?.lines || []) as string[];
		const seen = new Map<string, number>();
		return raw.map((text) => {
			const count = seen.get(text) ?? 0;
			seen.set(text, count + 1);
			return { text, key: count ? `${text}#${count}` : text };
		});
	}, [data]);

	useEffect(() => {
		const box = boxRef.current;
		if (!box || paused) return;
		if ((data?.lines as string[] | undefined)?.length)
			box.scrollTop = box.scrollHeight;
	}, [data, paused]);

	return (
		<div className="space-y-2">
			<div className="flex flex-wrap items-center gap-2">
				<span className="font-mono text-xs text-muted-foreground">
					{(data?.file as string) || "log file"}
				</span>
				<div className="ml-auto flex items-center gap-2">
					<select
						aria-label="Tail length"
						value={String(lines)}
						onChange={(e) => setLinesCount(Number(e.target.value))}
						className="h-8 rounded-md border border-input bg-card px-2 text-xs"
					>
						<option value="100">100 lines</option>
						<option value="200">200 lines</option>
						<option value="500">500 lines</option>
						<option value="1000">1000 lines</option>
					</select>
					<Button
						variant="outline"
						size="sm"
						onClick={() => setPaused((p) => !p)}
					>
						{paused ? (
							<Play className="h-3.5 w-3.5" />
						) : (
							<Pause className="h-3.5 w-3.5" />
						)}
						{paused ? "Resume" : "Pause"}
					</Button>
					<Badge variant={paused ? "warn" : "success"}>
						{paused ? "paused" : "live · 3s"}
					</Badge>
				</div>
			</div>
			{error && (
				<p className="py-4 text-sm text-destructive">Failed: {error.message}</p>
			)}
			{!error && (
				<div
					ref={boxRef}
					className="max-h-[60vh] min-h-40 overflow-auto rounded-lg bg-zinc-950 p-3 font-mono text-xs leading-relaxed"
				>
					{isLoading && !data && (
						<p className="text-zinc-400">Loading log tail…</p>
					)}
					{data && (data.error as string) && (
						<p className="text-amber-400">{String(data.error)}</p>
					)}
					{logLines.map(({ text, key }) => {
						const cls =
							text.includes("ERROR") || text.includes("Traceback")
								? "text-red-400"
								: text.includes("WARN")
									? "text-amber-400"
									: text.startsWith("[")
										? "text-cyan-300"
										: "text-zinc-300";
						return (
							<div key={key} className={`whitespace-pre-wrap ${cls}`}>
								{text}
							</div>
						);
					})}
					{data && !logLines.length && !data.error && (
						<p className="text-zinc-400">No log lines.</p>
					)}
				</div>
			)}
		</div>
	);
}

export default function ServerPage() {
	const [section, setSection] = useState("system");
	const isLogs = section === "logs";
	const { data, error, isLoading, mutate } = useServerSection(
		isLogs ? null : section,
		5000,
	);

	const sys = !isLogs && data?.ok && data.data ? data.data : null;
	const mem = sys?.mem;
	const disk = sys?.disk;
	const cpu = sys?.cpu;
	const loadPct =
		cpu && cpu.cores
			? Math.min(100, Math.round((cpu.load1 / cpu.cores) * 100))
			: null;

	return (
		<div className="space-y-5">
			<div>
				<h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
					<Server className="h-5 w-5" /> Server Diagnostics
				</h1>
				<p className="text-sm text-muted-foreground">
					Read-only proxy of the game server&apos;s own admin API (:8080) plus
					the process log tail. Sections auto-refresh every 5s.
				</p>
			</div>

			<Tabs
				value={section}
				onValueChange={setSection}
				items={SECTIONS.map((s) => ({ value: s.id, label: s.label }))}
			/>

			{sys && (
				<div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-4">
					<MiniStat
						icon={Timer}
						label="Uptime"
						value={sys.uptimeStr}
						color="text-orange-600 dark:text-orange-400"
					/>
					<MiniStat
						icon={Users}
						label="Players"
						value={sys.playerCount}
						color="text-blue-600 dark:text-blue-400"
					/>
					<MiniStat
						icon={Route}
						label="Routes"
						value={`${sys.routeCount} + ${sys.overrideCount} ovr`}
						color="text-violet-600 dark:text-violet-400"
					/>
					<MiniStat
						icon={Database}
						label="CDN files"
						value={sys.cdmFiles}
						color="text-amber-600 dark:text-amber-400"
					/>
					<MiniStat
						icon={ScrollText}
						label="Log lines"
						value={sys.logLines}
						color="text-cyan-600 dark:text-cyan-400"
					/>
					<MiniStat
						icon={MemoryStick}
						label="Memory"
						value={mem ? `${mem.used}/${mem.total} MB` : "-"}
						color="text-rose-600 dark:text-rose-400"
					/>
					<MiniStat
						icon={Cpu}
						label="CPU load"
						value={loadPct !== null ? `${loadPct}% (1m)` : "-"}
						color="text-emerald-600 dark:text-emerald-400"
					/>
					<MiniStat
						icon={HardDrive}
						label="Disk"
						value={disk ? `${disk.used}/${disk.total} GB` : "-"}
						color="text-lime-600 dark:text-lime-400"
					/>
				</div>
			)}

			<Card>
				{isLogs ? (
					<>
						<CardHeader>
							<div>
								<CardTitle className="flex items-center gap-2">
									<ScrollText className="h-4 w-4 text-muted-foreground" />{" "}
									Server log tail
								</CardTitle>
								<CardDescription>
									Last lines of the game server log file, newest at the bottom.
								</CardDescription>
							</div>
						</CardHeader>
						<CardContent>
							<LogsPanel />
						</CardContent>
					</>
				) : (
					<>
						<CardHeader>
							<div>
								<CardTitle className="flex items-center gap-2">
									<Server className="h-4 w-4 text-muted-foreground" />{" "}
									/api/server/{section}
								</CardTitle>
								<CardDescription>
									{data?.serverUrl || "proxying the game server"}
								</CardDescription>
							</div>
							<div className="flex shrink-0 items-center gap-3">
								{data && (
									<Badge variant={data.ok ? "success" : "danger"}>
										{data.ok ? `HTTP ${data.status}` : "down"}
									</Badge>
								)}
								<Button
									variant="ghost"
									size="icon"
									aria-label="Refresh section"
									className="h-8 w-8 text-muted-foreground hover:text-foreground"
									onClick={() => {
										void mutate();
									}}
								>
									<RefreshCw className="h-4 w-4" />
								</Button>
							</div>
						</CardHeader>
						<CardContent>
							{isLoading && !data && (
								<p className="py-8 text-sm text-muted-foreground">Loading...</p>
							)}
							{error && (
								<p className="py-8 text-sm text-destructive">
									Failed: {error.message}
								</p>
							)}
							{data && !data.ok && (
								<p className="py-8 flex items-center gap-2 text-sm text-muted-foreground">
									<AlertTriangle className="h-4 w-4 text-amber-500" />{" "}
									{data.error || "section unavailable"}
								</p>
							)}
							{data?.ok && <SectionBody section={section} data={data.data} />}
						</CardContent>
					</>
				)}
			</Card>
		</div>
	);
}

function SectionBody({ section, data }: { section: string; data: JsonValue }) {
	if (section === "routes") {
		const routeData =
			data && !Array.isArray(data) && typeof data === "object" ? data : {};
		const routes = Array.isArray(routeData.routes)
			? (routeData.routes as RouteRow[])
			: [];
		const total =
			typeof routeData.total === "number" ? routeData.total : routes.length;
		return (
			<div>
				<div className="mb-2 text-sm text-muted-foreground">
					{total} routes registered
				</div>
				<div className="max-h-[60vh] overflow-auto rounded-lg border border-border">
					<table className="w-full text-sm">
						<thead className="sticky top-0 bg-surface-2 text-left text-xs uppercase tracking-wide text-muted-foreground">
							<tr>
								<th className="px-3 py-2">Path</th>
								<th className="px-3 py-2">Model</th>
								<th className="px-3 py-2 text-right">Override</th>
							</tr>
						</thead>
						<tbody className="divide-y divide-border">
							{routes.map((r) => (
								<tr key={r.path} className="hover:bg-muted/30">
									<td className="px-3 py-1.5 font-mono text-xs">{r.path}</td>
									<td className="px-3 py-1.5 font-mono text-xs text-muted-foreground">
										{r.model}
									</td>
									<td className="px-3 py-1.5 text-right">
										{r.overridden ? (
											<Badge variant="success" className="text-[10px]">
												<CheckCircle2 className="h-3 w-3 mr-1" /> direct handler
											</Badge>
										) : (
											<span className="text-xs text-muted-foreground">-</span>
										)}
									</td>
								</tr>
							))}
						</tbody>
					</table>
				</div>
			</div>
		);
	}

	if (section === "cdn") {
		const cdnData =
			data && !Array.isArray(data) && typeof data === "object" ? data : {};
		const files = Array.isArray(cdnData.files)
			? (cdnData.files as CdnFile[])
			: [];
		const total =
			typeof cdnData.total === "number" ? cdnData.total : files.length;
		const fmt = (n: number) =>
			n > 1024 * 1024
				? `${(n / 1024 / 1024).toFixed(1)} MB`
				: n > 1024
					? `${(n / 1024).toFixed(1)} KB`
					: `${n} B`;
		return (
			<div>
				<div className="mb-2 text-sm text-muted-foreground">
					{total} files in the CDN bundle
				</div>
				<div className="max-h-[60vh] overflow-auto rounded-lg border border-border">
					<table className="w-full text-sm">
						<thead className="sticky top-0 bg-surface-2 text-left text-xs uppercase tracking-wide text-muted-foreground">
							<tr>
								<th className="px-3 py-2">File</th>
								<th className="px-3 py-2 text-right">Size</th>
							</tr>
						</thead>
						<tbody className="divide-y divide-border">
							{files.map((f) => (
								<tr key={f.name} className="hover:bg-muted/30">
									<td className="px-3 py-1.5 font-mono text-xs">{f.name}</td>
									<td className="px-3 py-1.5 text-right font-mono tnum text-xs text-muted-foreground">
										{fmt(f.size)}
									</td>
								</tr>
							))}
						</tbody>
					</table>
				</div>
			</div>
		);
	}

	return <JsonView data={data} />;
}
