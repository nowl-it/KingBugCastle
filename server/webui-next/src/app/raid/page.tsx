"use client";

import { useState } from "react";
import { useRaidAdmin, runMutation } from "@/lib/api";
import {
	Card,
	CardContent,
	CardHeader,
	CardTitle,
	CardDescription,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
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
import { Swords, RotateCcw, Pencil } from "lucide-react";

type RaidRow = {
	pid: string;
	clanId?: number | string;
	clanName: string;
	boss?: number;
	stage?: number;
	round?: number;
	killCount?: number;
	score?: number;
	remainHp?: number | null;
	remainBattleCount?: number | null;
	seeded: boolean;
};

const SET_FIELDS = [
	"killCount",
	"score",
	"remainHp",
	"round",
	"stage",
	"bossIndex",
] as const;
type SetField = (typeof SET_FIELDS)[number];

export default function RaidAdminPage() {
	const { data, mutate } = useRaidAdmin();
	const [editRow, setEditRow] = useState<RaidRow | null>(null);
	const [resetRow, setResetRow] = useState<RaidRow | null>(null);
	const [busy, setBusy] = useState(false);

	const raids: RaidRow[] = data?.raids ?? [];

	const doReset = async () => {
		if (!resetRow) return;
		setBusy(true);
		try {
			await runMutation(
				"/api/raid/admin/reset",
				{ method: "POST", body: JSON.stringify({ pid: resetRow.pid }) },
				`Raid reset for ${resetRow.clanName}`,
			);
			setResetRow(null);
			mutate();
		} finally {
			setBusy(false);
		}
	};

	return (
		<div className="space-y-5">
			<div>
				<h1 className="text-2xl font-semibold tracking-tight">
					Clan Raid Admin
				</h1>
				<p className="text-sm text-muted-foreground">
					Boss progress per clan. The panel only advances through real battles —
					use reset when a season needs re-seeding after testing.
				</p>
			</div>

			<Card>
				<CardHeader>
					<div>
						<CardTitle className="flex items-center gap-2">
							<Swords className="h-4 w-4" /> Clans ({raids.length})
						</CardTitle>
						<CardDescription>
							Rows appear once a player has joined or created a clan.
						</CardDescription>
					</div>
					<Button
						variant="outline"
						size="sm"
						onClick={() => {
							void mutate();
						}}
					>
						Refresh
					</Button>
				</CardHeader>
				<CardContent className="p-0">
					<Table compact>
						<TableHeader>
							<TableRow>
								<TableHead>Clan</TableHead>
								<TableHead className="text-right">Round</TableHead>
								<TableHead className="text-right">Stage</TableHead>
								<TableHead className="text-right">Boss</TableHead>
								<TableHead className="text-right">HP left</TableHead>
								<TableHead className="text-right">Kills</TableHead>
								<TableHead className="text-right">Score</TableHead>
								<TableHead className="text-right">Battles</TableHead>
								<TableHead className="w-28" />
							</TableRow>
						</TableHeader>
						<TableBody>
							{raids.map((r) => (
								<TableRow key={r.pid}>
									<TableCell>
										<div className="font-medium">
											{r.clanName || "(unnamed)"}
										</div>
										<div className="font-mono text-xs text-muted-foreground">
											{r.pid}
										</div>
									</TableCell>
									<TableCell className="tnum text-right">
										{r.round ?? "-"}
									</TableCell>
									<TableCell className="tnum text-right">
										{r.stage ?? "-"}
									</TableCell>
									<TableCell className="tnum text-right">
										{r.boss ?? "-"}
									</TableCell>
									<TableCell className="tnum text-right">
										{r.remainHp != null ? r.remainHp.toLocaleString() : "-"}
									</TableCell>
									<TableCell className="tnum text-right">
										{r.killCount ?? 0}
									</TableCell>
									<TableCell className="tnum text-right">
										{r.score ?? 0}
									</TableCell>
									<TableCell className="tnum text-right">
										{r.remainBattleCount != null ? (
											<Badge
												variant={r.remainBattleCount > 0 ? "warn" : "neutral"}
											>
												{r.remainBattleCount}
											</Badge>
										) : (
											"-"
										)}
									</TableCell>
									<TableCell>
										<div className="flex justify-end gap-1">
											<Button
												variant="ghost"
												size="sm"
												title="Edit fields"
												onClick={() => setEditRow(r)}
											>
												<Pencil className="h-4 w-4" />
											</Button>
											<Button
												variant="ghost"
												size="sm"
												title="Reset raid"
												onClick={() => setResetRow(r)}
											>
												<RotateCcw className="h-4 w-4" />
											</Button>
										</div>
									</TableCell>
								</TableRow>
							))}
							{raids.length === 0 && (
								<TableRow>
									<TableCell
										colSpan={9}
										className="py-12 text-center text-muted-foreground"
									>
										No clans yet.
									</TableCell>
								</TableRow>
							)}
						</TableBody>
					</Table>
				</CardContent>
			</Card>

			{/* Reset confirm */}
			<Dialog open={!!resetRow} onClose={() => setResetRow(null)}>
				<DialogHeader onClose={() => setResetRow(null)}>
					<DialogTitle>Reset raid — {resetRow?.clanName}</DialogTitle>
					<p className="mt-1 text-sm text-muted-foreground">
						Clears the stored raid state. The game re-seeds a fresh raid
						(current boss lineup, full HP) the next time the clan opens the raid
						panel.
					</p>
				</DialogHeader>
				<DialogFooter>
					<Button variant="ghost" onClick={() => setResetRow(null)}>
						Cancel
					</Button>
					<Button variant="destructive" disabled={busy} onClick={doReset}>
						{busy ? "Resetting…" : "Reset raid"}
					</Button>
				</DialogFooter>
			</Dialog>

			{editRow && (
				<RaidEditDialog
					row={editRow}
					onDone={() => {
						setEditRow(null);
						mutate();
					}}
					onClose={() => setEditRow(null)}
				/>
			)}
		</div>
	);
}

function RaidEditDialog({
	row,
	onDone,
	onClose,
}: {
	row: RaidRow;
	onDone: () => void;
	onClose: () => void;
}) {
	const [field, setField] = useState<SetField>("killCount");
	const [value, setValue] = useState("");
	const [busy, setBusy] = useState(false);

	const apply = async () => {
		setBusy(true);
		try {
			await runMutation(
				"/api/raid/admin/set",
				{
					method: "POST",
					body: JSON.stringify({ pid: row.pid, field, value: Number(value) }),
				},
				`${field} set for ${row.clanName}`,
			);
			onDone();
		} finally {
			setBusy(false);
		}
	};

	return (
		<Dialog open onClose={onClose}>
			<DialogHeader onClose={onClose}>
				<DialogTitle>Edit raid — {row.clanName}</DialogTitle>
				<p className="mt-1 text-sm text-muted-foreground">
					Overrides one field of the stored raid state (integers only).
				</p>
			</DialogHeader>
			<DialogContent className="space-y-3">
				<div className="space-y-1">
					<label htmlFor="raid-field" className="text-xs text-muted-foreground">
						Field
					</label>
					<select
						id="raid-field"
						value={field}
						onChange={(e) => setField(e.target.value as SetField)}
						className="h-9 w-full rounded-md border border-input bg-card px-3 text-sm"
					>
						{SET_FIELDS.map((f) => (
							<option key={f} value={f}>
								{f}
							</option>
						))}
					</select>
				</div>
				<div className="space-y-1">
					<label htmlFor="raid-value" className="text-xs text-muted-foreground">
						Value
					</label>
					<Input
						id="raid-value"
						type="number"
						min={0}
						value={value}
						onChange={(e) => setValue(e.target.value)}
					/>
				</div>
				<p className="text-xs text-muted-foreground">
					Current: {field} = {String(row[field as keyof RaidRow] ?? "-")}
				</p>
			</DialogContent>
			<DialogFooter>
				<Button variant="ghost" onClick={onClose}>
					Cancel
				</Button>
				<Button
					disabled={busy || value === "" || Number(value) < 0}
					onClick={apply}
				>
					{busy ? "Saving…" : "Apply"}
				</Button>
			</DialogFooter>
		</Dialog>
	);
}
