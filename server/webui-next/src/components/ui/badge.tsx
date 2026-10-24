import * as React from "react";
import { cn } from "@/lib/utils";

export interface BadgeProps extends React.HTMLAttributes<HTMLDivElement> {
	variant?:
		| "default"
		| "secondary"
		| "destructive"
		| "outline"
		| "success"
		| "warn"
		| "danger"
		| "neutral";
}

function Badge({ className, variant = "neutral", ...props }: BadgeProps) {
	return (
		<div
			className={cn(
				"inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium transition-colors",
				{
					"border-transparent bg-primary text-primary-foreground":
						variant === "default",
					"border-transparent bg-secondary text-secondary-foreground":
						variant === "secondary",
					"border-transparent bg-destructive text-destructive-foreground":
						variant === "destructive",
					"text-foreground": variant === "outline",
					// semantic status badges
					"border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/15 dark:text-emerald-400":
						variant === "success",
					"border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-500/30 dark:bg-amber-500/15 dark:text-amber-400":
						variant === "warn",
					"border-red-200 bg-red-50 text-red-700 dark:border-red-500/30 dark:bg-red-500/15 dark:text-red-400":
						variant === "danger",
					"border-border bg-muted text-muted-foreground": variant === "neutral",
				},
				className,
			)}
			{...props}
		/>
	);
}

export { Badge };
