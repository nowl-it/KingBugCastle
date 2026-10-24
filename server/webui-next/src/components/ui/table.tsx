import * as React from "react";
import { cn } from "@/lib/utils";

// Compact mode shrinks every cell in a table at once: pass `compact` on <Table>
// instead of repeating padding overrides on each row/cell.
const TableContext = React.createContext<{ compact: boolean }>({
	compact: false,
});

const Table = React.forwardRef<
	HTMLTableElement,
	React.HTMLAttributes<HTMLTableElement> & { compact?: boolean }
>(({ className, compact = false, ...props }, ref) => (
	<TableContext.Provider value={{ compact }}>
		<div className="relative w-full overflow-auto">
			<table
				ref={ref}
				className={cn("w-full caption-bottom text-sm", className)}
				{...props}
			/>
		</div>
	</TableContext.Provider>
));
Table.displayName = "Table";

const TableHeader = React.forwardRef<
	HTMLTableSectionElement,
	React.HTMLAttributes<HTMLTableSectionElement>
>(({ className, ...props }, ref) => (
	<thead
		ref={ref}
		className={cn(
			"sticky top-0 z-10 [&_tr]:border-b [&_tr]:bg-surface-2",
			className,
		)}
		{...props}
	/>
));
TableHeader.displayName = "TableHeader";

const TableBody = React.forwardRef<
	HTMLTableSectionElement,
	React.HTMLAttributes<HTMLTableSectionElement>
>(({ className, ...props }, ref) => (
	<tbody
		ref={ref}
		className={cn("[&_tr:last-child]:border-0", className)}
		{...props}
	/>
));
TableBody.displayName = "TableBody";

const TableFooter = React.forwardRef<
	HTMLTableSectionElement,
	React.HTMLAttributes<HTMLTableSectionElement>
>(({ className, ...props }, ref) => (
	<tfoot
		ref={ref}
		className={cn(
			"border-t bg-muted/50 font-medium [&>tr]:last:border-b-0",
			className,
		)}
		{...props}
	/>
));
TableFooter.displayName = "TableFooter";

const TableRow = React.forwardRef<
	HTMLTableRowElement,
	React.HTMLAttributes<HTMLTableRowElement>
>(({ className, ...props }, ref) => (
	<tr
		ref={ref}
		className={cn(
			"border-b border-border/70 bg-card transition-colors hover:bg-surface-2 data-[state=selected]:bg-muted",
			className,
		)}
		{...props}
	/>
));
TableRow.displayName = "TableRow";

const TableHead = React.forwardRef<
	HTMLTableCellElement,
	React.ThHTMLAttributes<HTMLTableCellElement>
>(({ className, ...props }, ref) => {
	const { compact } = React.useContext(TableContext);
	return (
		<th
			ref={ref}
			className={cn(
				"text-left align-middle font-medium text-muted-foreground [&:has([role=checkbox])]:pr-0",
				compact ? "h-9 px-3 text-xs" : "h-11 px-4",
				className,
			)}
			{...props}
		/>
	);
});
TableHead.displayName = "TableHead";

const TableCell = React.forwardRef<
	HTMLTableCellElement,
	React.TdHTMLAttributes<HTMLTableCellElement>
>(({ className, ...props }, ref) => {
	const { compact } = React.useContext(TableContext);
	return (
		<td
			ref={ref}
			className={cn(
				"align-middle [&:has([role=checkbox])]:pr-0",
				compact ? "px-3 py-1.5" : "p-4",
				className,
			)}
			{...props}
		/>
	);
});
TableCell.displayName = "TableCell";

const TableCaption = React.forwardRef<
	HTMLTableCaptionElement,
	React.HTMLAttributes<HTMLTableCaptionElement>
>(({ className, ...props }, ref) => (
	<caption
		ref={ref}
		className={cn("mt-4 text-sm text-muted-foreground", className)}
		{...props}
	/>
));
TableCaption.displayName = "TableCaption";

export {
	Table,
	TableHeader,
	TableBody,
	TableFooter,
	TableHead,
	TableRow,
	TableCell,
	TableCaption,
};
