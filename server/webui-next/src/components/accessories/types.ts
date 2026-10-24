export type BuilderChoice = { id: number; name: string };
export type BuilderOptions = {
	types: BuilderChoice[];
	rarities: BuilderChoice[];
	synergies: BuilderChoice[];
	mainStatsByType: Record<string, string[]>;
	subStatKeys: string[];
	scoreMax: number;
	builtinCount: number;
	slotsByRarity: Record<string, number>;
	budgetByRarity: Record<string, number>;
};
export type AdminEntry = {
	name: string;
	type: number | string;
	rarity: number;
	level: number;
	synergy: number;
	mainStat: string;
	subStats: { key: string; value: number }[];
};
export type AdminConfig = {
	include_builtin: boolean;
	accessories: AdminEntry[];
};
export type AccessorySubStat = {
	label: string;
	score?: number;
	grade?: string;
};
export type Accessory = {
	id: number;
	typeName: string;
	synergyName: string;
	rarityName: string;
	level: number;
	unitName?: string;
	scoreTotal: number;
	mainStatLabel?: string;
	subStats?: AccessorySubStat[];
};
export type AccessoriesResponse = {
	scoreRange?: Record<string, string | number>;
	grades?: Record<string, string | number>;
	accessories?: Accessory[];
};
export type SubStatRow = { key: string; value: string };
export type AccessoryDraft = { entry: AdminEntry; index: number | null };
