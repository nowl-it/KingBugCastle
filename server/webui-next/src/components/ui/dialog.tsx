"use client";

import * as React from "react";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

// Headless modal on the native <dialog> element: no portal library, focus
// trap and Esc-to-close come from the browser. open/onClose drive it.
interface DialogProps {
	open: boolean;
	onClose: () => void;
	children: React.ReactNode;
	className?: string;
	wide?: boolean;
}

function Dialog({ open, onClose, children, className, wide }: DialogProps) {
	const ref = React.useRef<HTMLDialogElement>(null);

	React.useEffect(() => {
		const el = ref.current;
		if (!el) return;
		if (open && !el.open) el.showModal();
		if (!open && el.open) el.close();
	}, [open]);

	return (
		<dialog
			ref={ref}
			onClose={onClose}
			onMouseDown={(e) => {
				// Backdrop click: the click lands on the dialog box itself, not content.
				if (e.target === ref.current) onClose();
			}}
			className={cn(
				"m-auto rounded-xl border bg-card p-0 text-card-foreground shadow-card",
				"backdrop:bg-black/40 open:animate-[dialog-in_160ms_ease-out]",
				wide ? "w-[min(92vw,56rem)]" : "w-[min(92vw,32rem)]",
				className,
			)}
		>
			{children}
		</dialog>
	);
}

function DialogHeader({
	className,
	children,
	onClose,
}: React.HTMLAttributes<HTMLDivElement> & { onClose?: () => void }) {
	return (
		<div
			className={cn(
				"flex items-start justify-between gap-4 border-b px-5 py-4",
				className,
			)}
		>
			<div className="min-w-0">{children}</div>
			{onClose && (
				<button
					type="button"
					onClick={onClose}
					aria-label="Close"
					className="rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
				>
					<X size={16} />
				</button>
			)}
		</div>
	);
}

function DialogTitle({
	className,
	...props
}: React.HTMLAttributes<HTMLHeadingElement>) {
	return (
		<h2
			className={cn("text-base font-semibold tracking-tight", className)}
			{...props}
		/>
	);
}

function DialogDescription({
	className,
	...props
}: React.HTMLAttributes<HTMLParagraphElement>) {
	return (
		<p
			className={cn("mt-1 text-sm text-muted-foreground", className)}
			{...props}
		/>
	);
}

function DialogContent({
	className,
	...props
}: React.HTMLAttributes<HTMLDivElement>) {
	return <div className={cn("px-5 py-4", className)} {...props} />;
}

function DialogFooter({
	className,
	...props
}: React.HTMLAttributes<HTMLDivElement>) {
	return (
		<div
			className={cn(
				"flex items-center justify-end gap-2 border-t px-5 py-4",
				className,
			)}
			{...props}
		/>
	);
}

export {
	Dialog,
	DialogHeader,
	DialogTitle,
	DialogDescription,
	DialogContent,
	DialogFooter,
};
