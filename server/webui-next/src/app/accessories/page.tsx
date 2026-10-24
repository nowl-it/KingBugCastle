"use client";

import { useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Gem } from "lucide-react";
import { fetcher, runMutation, useAccessories } from "@/lib/api";
import { PlayerBar, usePlayerSelection } from "@/components/player-context";
import { Tabs } from "@/components/ui/tabs";
import { AccessoryBuilder } from "@/components/accessories/builder";
import { AdminSetList } from "@/components/accessories/set-list";
import { PlayerInventory } from "@/components/accessories/inventory";
import type {
	AccessoriesResponse,
	AccessoryDraft,
	AdminConfig,
	BuilderOptions,
} from "@/components/accessories/types";

export default function AccessoriesPage() {
	const builderRef = useRef<HTMLDivElement>(null);
	const { selectedId } = usePlayerSelection();
	const { data, mutate: mutateAccessories } = useAccessories(
		selectedId || undefined,
	);
	const {
		data: optionsData,
		isLoading: optionsLoading,
		isError: optionsError,
	} = useQuery({
		queryKey: ["/api/admin-accessories/options"],
		queryFn: () => fetcher("/api/admin-accessories/options"),
	});
	const {
		data: configData,
		refetch: refetchConfig,
		isLoading: configLoading,
	} = useQuery({
		queryKey: ["/api/admin-accessories"],
		queryFn: () => fetcher("/api/admin-accessories"),
	});

	const [applying, setApplying] = useState(false);
	const [view, setView] = useState<"build" | "inventory">("build");
	const [draft, setDraft] = useState<AccessoryDraft | null>(null);
	const [draftNonce, setDraftNonce] = useState(0);

	const options = optionsData as BuilderOptions | undefined;
	const config = configData as AdminConfig | undefined;
	const owned = data as AccessoriesResponse | undefined;
	const adminList = config?.accessories || [];
	const builtinCount = options?.builtinCount ?? 65;
	const deploymentCount =
		adminList.length + (config?.include_builtin ? builtinCount : 0);
	const typeNames = new Map(
		(options?.types || []).map((entry) => [entry.id, entry.name]),
	);
	const rarityNames = new Map(
		(options?.rarities || []).map((entry) => [entry.id, entry.name]),
	);
	const synergyNames = new Map(
		(options?.synergies || []).map((entry) => [entry.id, entry.name]),
	);

	const openDraft = (nextDraft: AccessoryDraft) => {
		setDraft(nextDraft);
		setDraftNonce((nonce) => nonce + 1);
		requestAnimationFrame(() =>
			builderRef.current?.scrollIntoView({
				behavior: "smooth",
				block: "start",
			}),
		);
	};

	const updateBuiltin = async (include: boolean) => {
		await runMutation(
			"/api/admin-accessories/config",
			{
				method: "POST",
				body: JSON.stringify({ include_builtin: include }),
			},
			include ? "Built-in set enabled" : "Built-in set disabled",
		);
		refetchConfig();
	};

	const deleteEntry = async (index: number) => {
		await runMutation(
			"/api/admin-accessories/delete",
			{
				method: "POST",
				body: JSON.stringify({ index }),
			},
			"Accessory removed",
		);
		if (draft?.index === index) setDraft(null);
		refetchConfig();
	};

	const applyToPlayer = async () => {
		if (!selectedId || !deploymentCount) return;
		if (
			!window.confirm(
				`Replace all accessories for ${selectedId} with ${deploymentCount} items?`,
			)
		)
			return;
		setApplying(true);
		try {
			await runMutation(
				"/api/admin-accessories/apply",
				{
					method: "POST",
					body: JSON.stringify({ pid: selectedId }),
				},
				"Admin set applied to player",
			);
			mutateAccessories();
		} finally {
			setApplying(false);
		}
	};

	return (
		<div className="space-y-5">
			<div>
				<h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
					<Gem className="h-5 w-5" /> Accessories
				</h1>
				<p className="text-sm text-muted-foreground">
					Build one admin set, then replace a player&apos;s accessories with it.
				</p>
			</div>

			<PlayerBar />

			<div className="grid gap-px overflow-hidden rounded-xl border bg-border sm:grid-cols-3">
				{[
					["1", "Add accessories", "Each save adds one item to the admin set."],
					[
						"2",
						"Review the set",
						`${adminList.length} custom + ${config?.include_builtin ? builtinCount : 0} built-in items.`,
					],
					[
						"3",
						"Apply to player",
						`${deploymentCount} items will replace the player's current set.`,
					],
				].map(([step, title, description]) => (
					<div key={step} className="flex gap-3 bg-card p-4">
						<span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary text-xs font-semibold text-primary-foreground tnum">
							{step}
						</span>
						<div>
							<p className="text-sm font-medium">{title}</p>
							<p className="mt-0.5 text-xs leading-5 text-muted-foreground">
								{description}
							</p>
						</div>
					</div>
				))}
			</div>

			<Tabs
				value={view}
				onValueChange={(value) => setView(value as "build" | "inventory")}
				items={[
					{
						value: "build",
						label: (
							<>
								Build set{" "}
								<span className="ml-1 text-xs text-muted-foreground tnum">
									{adminList.length}
								</span>
							</>
						),
					},
					{
						value: "inventory",
						label: (
							<>
								Player inventory{" "}
								<span className="ml-1 text-xs text-muted-foreground tnum">
									{owned?.accessories?.length ?? 0}
								</span>
							</>
						),
					},
				]}
				className="w-fit border-b-0"
			/>

			{view === "build" ? (
				<div className="grid items-start gap-5 xl:grid-cols-[minmax(360px,480px)_minmax(0,1fr)]">
					<div ref={builderRef} className="scroll-mt-20 xl:sticky xl:top-20">
						<AccessoryBuilder
							key={
								draft
									? `${draft.index ?? "copy"}-${draftNonce}`
									: `new-${draftNonce}`
							}
							options={options}
							optionsLoading={optionsLoading}
							optionsError={optionsError}
							draft={draft}
							onSaved={() => {
								refetchConfig();
							}}
							onResetDraft={() => setDraft(null)}
						/>
					</div>
					<AdminSetList
						adminList={adminList}
						typeNames={typeNames}
						rarityNames={rarityNames}
						synergyNames={synergyNames}
						includeBuiltin={config?.include_builtin ?? false}
						builtinCount={builtinCount}
						deploymentCount={deploymentCount}
						loading={configLoading}
						selectedId={selectedId}
						applying={applying}
						draft={draft}
						onApply={applyToPlayer}
						onToggleBuiltin={updateBuiltin}
						onEdit={openDraft}
						onDelete={deleteEntry}
					/>
				</div>
			) : (
				<PlayerInventory owned={owned} selectedId={selectedId} />
			)}
		</div>
	);
}
