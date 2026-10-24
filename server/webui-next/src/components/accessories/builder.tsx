"use client";

import { useState, type FormEvent } from "react";
import {
	AlertTriangle,
	Diamond,
	Loader2,
	Plus,
	RotateCcw,
	Save,
	Trash2,
} from "lucide-react";
import { runMutation } from "@/lib/api";
import { Button } from "@/components/ui/button";
import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import type { AccessoryDraft, BuilderOptions, SubStatRow } from "./types";

type LocalSubStatRow = SubStatRow & { rid: number };

let rowIdCounter = 0;
const nextRowId = () => ++rowIdCounter;

function Field({
	label,
	hint,
	htmlFor,
	children,
}: {
	label: string;
	hint?: string;
	htmlFor: string;
	children: React.ReactNode;
}) {
	return (
		<div className="grid gap-1.5">
			<label
				htmlFor={htmlFor}
				className="flex items-center justify-between gap-3 text-xs font-medium text-foreground"
			>
				{label}
				{hint && (
					<span className="font-mono font-normal text-muted-foreground">
						{hint}
					</span>
				)}
			</label>
			{children}
		</div>
	);
}

function SubStatRows({
	options,
	rows,
	max,
	onChange,
}: {
	options: string[];
	rows: LocalSubStatRow[];
	max: number;
	onChange: (rows: LocalSubStatRow[]) => void;
}) {
	const set = (rid: number, patch: Partial<SubStatRow>) => {
		onChange(rows.map((row) => (row.rid === rid ? { ...row, ...patch } : row)));
	};

	return (
		<div className="grid gap-2">
			{rows.map((row, index) => (
				<div
					key={row.rid}
					className="grid grid-cols-[minmax(0,1fr)_5.5rem_2.25rem] items-center gap-2"
				>
					<Select
						aria-label={`Sub-stat ${index + 1}`}
						value={row.key}
						onChange={(event) => set(row.rid, { key: event.target.value })}
					>
						{options.map((key) => (
							<option key={key} value={key}>
								{key}
							</option>
						))}
					</Select>
					<Input
						aria-label={`Sub-stat ${index + 1} score`}
						type="number"
						step="0.1"
						min={0}
						max={max}
						value={row.value}
						onChange={(event) => set(row.rid, { value: event.target.value })}
						className="font-mono tnum"
					/>
					<Button
						type="button"
						variant="ghost"
						size="icon"
						aria-label={`Remove sub-stat ${index + 1}`}
						disabled={rows.length === 1}
						className="h-9 w-9 text-muted-foreground hover:text-destructive"
						onClick={() => onChange(rows.filter((r) => r.rid !== row.rid))}
					>
						<Trash2 className="h-4 w-4" />
					</Button>
				</div>
			))}
		</div>
	);
}

// The parent remounts this component (via `key`) whenever the draft changes,
// so initial state can be read straight from `draft` without sync effects.
export function AccessoryBuilder({
	options,
	optionsLoading,
	optionsError,
	draft,
	onSaved,
	onResetDraft,
}: {
	options: BuilderOptions | undefined;
	optionsLoading: boolean;
	optionsError: boolean;
	draft: AccessoryDraft | null;
	onSaved: () => void;
	onResetDraft: () => void;
}) {
	const entry = draft?.entry;
	const editingIndex = draft ? draft.index : null;

	const resolveTypeName = (value: number | string) =>
		typeof value === "number"
			? options?.types.find((choice) => choice.id === value)?.name || "Necklace"
			: value;

	const [name, setName] = useState(
		entry ? (editingIndex === null ? `${entry.name} copy` : entry.name) : "",
	);
	const [type, setType] = useState(
		entry ? resolveTypeName(entry.type) : "Necklace",
	);
	const [rarity, setRarity] = useState(String(entry?.rarity ?? 3));
	const [level, setLevel] = useState(String(entry?.level ?? 20));
	const [synergy, setSynergy] = useState(String(entry?.synergy ?? 0));
	const [mainStat, setMainStat] = useState(entry?.mainStat || "AtkPer");
	const [subStats, setSubStats] = useState<LocalSubStatRow[]>(
		entry?.subStats?.length
			? entry.subStats.map((stat) => ({
					key: stat.key,
					value: String(stat.value),
					rid: nextRowId(),
				}))
			: [{ key: "BaseDefPen", value: "26", rid: nextRowId() }],
	);
	const [saving, setSaving] = useState(false);

	const mainStats = options?.mainStatsByType[type] || [];
	const slots = options?.slotsByRarity[rarity] || 1;
	const budget = options?.budgetByRarity[rarity] || 0;
	const subKeys = options?.subStatKeys || [];
	const scoreMax = options?.scoreMax ?? 26;
	const shownSubStats = subStats.slice(0, slots);
	const subStatsTotal = shownSubStats.reduce(
		(total, row) => total + (parseFloat(row.value) || 0),
		0,
	);
	const budgetPercent = budget
		? Math.min(100, (subStatsTotal / budget) * 100)
		: 0;
	const overBudget = subStatsTotal > budget + 0.001;
	const canSave =
		Boolean(name.trim()) && !overBudget && !optionsLoading && !optionsError;

	const submit = async (event: FormEvent) => {
		event.preventDefault();
		if (!canSave) return;
		setSaving(true);
		try {
			await runMutation(
				editingIndex === null
					? "/api/admin-accessories"
					: "/api/admin-accessories/update",
				{
					method: "POST",
					body: JSON.stringify({
						...(editingIndex === null ? {} : { index: editingIndex }),
						name: name.trim(),
						type,
						rarity: Number(rarity),
						level: Number(level),
						synergy: Number(synergy),
						mainStat,
						subStats: shownSubStats.map((row) => ({
							key: row.key,
							value: parseFloat(row.value) || 0,
						})),
					}),
				},
				editingIndex === null
					? "Accessory added to the admin set"
					: "Accessory updated",
			);
			onResetDraft();
			onSaved();
		} finally {
			setSaving(false);
		}
	};

	const reset = () => {
		onResetDraft();
		setName("");
		setType("Necklace");
		setRarity("3");
		setLevel("20");
		setSynergy("0");
		setMainStat(options?.mainStatsByType.Necklace?.[0] || "AtkPer");
		setSubStats([
			{ key: subKeys[0] || "AtkPer", value: "26", rid: nextRowId() },
		]);
	};

	return (
		<form onSubmit={submit}>
			<Card>
				<CardHeader>
					<div className="min-w-0">
						<CardTitle className="flex items-center gap-2">
							<Diamond className="h-4 w-4 text-muted-foreground" />{" "}
							{editingIndex === null
								? "1. Add one accessory"
								: `Editing item ${editingIndex + 1}`}
						</CardTitle>
						<CardDescription>
							{editingIndex === null
								? "Saving adds this accessory to the set shown on the right. It does not change a player yet."
								: "Save updates this item in place without changing the rest of the set."}
						</CardDescription>
					</div>
				</CardHeader>
				<CardContent className="space-y-4">
					{optionsError && (
						<div
							role="alert"
							className="flex items-center gap-2 border-l-2 border-destructive bg-destructive/5 px-3 py-2 text-xs text-destructive"
						>
							<AlertTriangle className="h-3.5 w-3.5 shrink-0" /> Builder rules
							could not be loaded. Refresh before creating an accessory.
						</div>
					)}
					<Field label="Name" hint="required" htmlFor="acc-name">
						<Input
							id="acc-name"
							value={name}
							onChange={(event) => setName(event.target.value)}
							placeholder="e.g. Menace necklace"
							autoComplete="off"
						/>
					</Field>

					<div className="grid gap-3 sm:grid-cols-3 xl:grid-cols-2">
						<Field label="Type" htmlFor="acc-type">
							<Select
								id="acc-type"
								value={type}
								onChange={(event) => {
									setType(event.target.value);
									setMainStat(
										options?.mainStatsByType[event.target.value]?.[0] ||
											"AtkPer",
									);
								}}
							>
								{(options?.types || []).map((choice) => (
									<option key={choice.id} value={choice.name}>
										{choice.name}
									</option>
								))}
							</Select>
						</Field>
						<Field label="Rarity" hint={`${slots} stats`} htmlFor="acc-rarity">
							<Select
								id="acc-rarity"
								value={rarity}
								onChange={(event) => setRarity(event.target.value)}
							>
								{(options?.rarities || []).map((choice) => (
									<option key={choice.id} value={String(choice.id)}>
										{choice.name}
									</option>
								))}
							</Select>
						</Field>
						<Field label="Level" htmlFor="acc-level">
							<Input
								id="acc-level"
								type="number"
								min={1}
								max={20}
								value={level}
								onChange={(event) => setLevel(event.target.value)}
								className="font-mono tnum"
							/>
						</Field>
						<Field label="Synergy" htmlFor="acc-synergy">
							<Select
								id="acc-synergy"
								value={synergy}
								onChange={(event) => setSynergy(event.target.value)}
							>
								{(options?.synergies || []).map((choice) => (
									<option key={choice.id} value={String(choice.id)}>
										{choice.name}
									</option>
								))}
							</Select>
						</Field>
					</div>

					<Field label="Main stat" hint={type} htmlFor="acc-mainstat">
						<Select
							id="acc-mainstat"
							value={mainStat}
							onChange={(event) => setMainStat(event.target.value)}
						>
							{mainStats.map((key) => (
								<option key={key} value={key}>
									{key}
								</option>
							))}
						</Select>
					</Field>

					<fieldset className="space-y-3 rounded-lg border p-3">
						<div className="flex items-center justify-between gap-3">
							<legend className="text-xs font-medium">Sub-stats</legend>
							<span
								className={`font-mono text-xs tnum ${overBudget ? "text-destructive" : "text-muted-foreground"}`}
							>
								{subStatsTotal.toFixed(1)} / {budget.toFixed(1)} points
							</span>
						</div>
						<div className="h-1.5 overflow-hidden rounded-full bg-muted">
							<div
								className={`h-full rounded-full transition-all ${overBudget ? "bg-destructive" : "bg-primary"}`}
								style={{ width: `${budgetPercent}%` }}
							/>
						</div>
						<SubStatRows
							options={subKeys}
							rows={shownSubStats}
							max={scoreMax}
							onChange={setSubStats}
						/>
						<div className="flex items-center justify-between gap-3">
							{shownSubStats.length < slots ? (
								<Button
									type="button"
									variant="outline"
									size="sm"
									onClick={() =>
										setSubStats([
											...shownSubStats,
											{
												key: subKeys[0] || "AtkPer",
												value: "4",
												rid: nextRowId(),
											},
										])
									}
								>
									<Plus className="mr-1 h-3.5 w-3.5" /> Add stat
								</Button>
							) : (
								<span />
							)}
							<span className="text-xs text-muted-foreground">
								Max {scoreMax.toFixed(1)} each
							</span>
						</div>
						{overBudget && (
							<p className="text-xs font-medium text-destructive">
								Reduce the total by {(subStatsTotal - budget).toFixed(1)}{" "}
								points.
							</p>
						)}
					</fieldset>

					<div className="flex flex-col-reverse gap-2 border-t pt-4 sm:flex-row sm:justify-between">
						<Button type="button" variant="ghost" onClick={reset}>
							<RotateCcw className="mr-1.5 h-4 w-4" /> Reset
						</Button>
						<Button type="submit" disabled={!canSave || saving}>
							{saving ? (
								<Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
							) : (
								<Save className="mr-1.5 h-4 w-4" />
							)}{" "}
							{editingIndex === null ? "Add to set" : "Save changes"}
						</Button>
					</div>
				</CardContent>
			</Card>
		</form>
	);
}
