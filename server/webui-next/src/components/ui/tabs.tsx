"use client";

import * as React from "react";
import { cn } from "@/lib/utils";

// Minimal controlled tabs: value + onChange live in the page state, this just
// renders the trigger row and wires aria attributes. Panels are rendered by
// the page behind `{tab === "..." && ...}` guards.
interface TabsProps {
	value: string;
	onValueChange: (v: string) => void;
	items: { value: string; label: React.ReactNode }[];
	className?: string;
}

function Tabs({ value, onValueChange, items, className }: TabsProps) {
	return (
		<div
			role="tablist"
			aria-orientation="horizontal"
			className={cn("flex flex-wrap items-center gap-1 border-b", className)}
		>
			{items.map((item) => {
				const active = item.value === value;
				return (
					<button
						key={item.value}
						type="button"
						role="tab"
						aria-selected={active}
						onClick={() => onValueChange(item.value)}
						className={cn(
							"-mb-px rounded-t-md border-b-2 px-3 py-2 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
							active
								? "border-primary text-foreground"
								: "border-transparent text-muted-foreground hover:text-foreground",
						)}
					>
						{item.label}
					</button>
				);
			})}
		</div>
	);
}

export { Tabs };
