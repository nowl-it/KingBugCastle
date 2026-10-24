"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useStatus, useWhoAmI, runMutation } from "@/lib/api";
import { ThemeToggle } from "@/components/theme-toggle";
import {
	LayoutDashboard,
	Users,
	UserRound,
	Package,
	Diamond,
	Mail,
	Server,
	Settings,
	LogOut,
	Menu,
	X,
	Database,
	ScrollText,
	HandHeart,
	Swords,
	History,
	ChevronRight,
} from "lucide-react";

const NAV_GROUPS: {
	title: string;
	items: {
		href: string;
		label: string;
		icon: React.ComponentType<{ className?: string }>;
	}[];
}[] = [
	{
		title: "Operations",
		items: [
			{ href: "/", label: "Overview", icon: LayoutDashboard },
			{ href: "/players", label: "Players", icon: Users },
			{ href: "/requests", label: "Requests", icon: ScrollText },
			{ href: "/donations", label: "Donations", icon: HandHeart },
		],
	},
	{
		title: "Content",
		items: [
			{ href: "/heroes", label: "Heroes", icon: UserRound },
			{ href: "/items", label: "Items", icon: Package },
			{ href: "/accessories", label: "Accessories", icon: Diamond },
			{ href: "/mail", label: "Mail", icon: Mail },
			{ href: "/gamedata", label: "Game Data", icon: Database },
		],
	},
	{
		title: "System",
		items: [
			{ href: "/raid", label: "Raid Admin", icon: Swords },
			{ href: "/server", label: "Diagnostics", icon: Server },
			{ href: "/audit", label: "Audit Log", icon: History },
			{ href: "/account", label: "Account", icon: Settings },
		],
	},
];

const ALL_ITEMS = NAV_GROUPS.flatMap((g) => g.items);

export function AppShell({ children }: { children: React.ReactNode }) {
	const pathname = usePathname();
	const { data: status } = useStatus();
	const { data: who, mutate: mutateWho } = useWhoAmI();
	const [navOpen, setNavOpen] = useState(false);

	const handleSignOut = async () => {
		await runMutation("/api/auth/logout", { method: "POST" });
		localStorage.removeItem("admin_token");
		mutateWho();
	};

	const isSystemOnline = status?.players !== undefined;
	const current = ALL_ITEMS.find((i) => i.href === pathname);
	const currentGroup = NAV_GROUPS.find((g) =>
		g.items.some((i) => i.href === pathname),
	);

	const handleNav = () => setNavOpen(false);

	const nav = (
		<nav className="flex h-full flex-col gap-y-7 px-4 py-6">
			{NAV_GROUPS.map((group) => (
				<div key={group.title}>
					<div className="mb-2 px-3 text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground/80">
						{group.title}
					</div>
					<ul className="flex flex-col gap-y-0.5">
						{group.items.map((item) => {
							const isActive = pathname === item.href;
							return (
								<li key={item.href}>
									<Link
										href={item.href}
										onClick={handleNav}
										aria-current={isActive ? "page" : undefined}
										className={`group flex items-center gap-x-2.5 rounded-full px-3 py-1.5 text-sm font-medium transition-colors ${
											isActive
												? "bg-primary text-primary-foreground"
												: "text-muted-foreground hover:bg-muted hover:text-foreground"
										}`}
									>
										<item.icon
											className={`h-4 w-4 shrink-0 ${isActive ? "text-primary-foreground" : "text-muted-foreground group-hover:text-foreground"}`}
										/>
										{item.label}
									</Link>
								</li>
							);
						})}
					</ul>
				</div>
			))}
		</nav>
	);

	return (
		<div className="flex min-h-screen flex-col bg-background text-foreground">
			<header className="sticky top-0 z-50 flex h-16 shrink-0 items-center gap-x-3 border-b border-border bg-card/80 px-4 backdrop-blur sm:gap-x-6 sm:px-6 lg:px-8">
				<button
					type="button"
					onClick={() => setNavOpen((v) => !v)}
					className="rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground lg:hidden"
					aria-label="Toggle navigation"
				>
					{navOpen ? <X size={20} /> : <Menu size={20} />}
				</button>

				<div className="flex flex-1 items-center gap-x-4 self-stretch lg:gap-x-6">
					<div className="flex items-center gap-2 font-semibold">
						<div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
							K
						</div>
						<span className="hidden sm:inline">KGC Admin</span>
					</div>

					{/* Breadcrumb */}
					{current && (
						<div className="hidden min-w-0 items-center gap-1.5 text-sm text-muted-foreground md:flex">
							<ChevronRight size={14} className="shrink-0" />
							<span className="hidden lg:inline">{currentGroup?.title}</span>
							<ChevronRight size={14} className="hidden shrink-0 lg:inline" />
							<span className="truncate font-medium text-foreground">
								{current.label}
							</span>
						</div>
					)}

					<div className="ml-auto flex items-center gap-x-4 lg:gap-x-6">
						<ThemeToggle />
						{isSystemOnline && (
							<span className="tnum hidden items-center gap-1.5 rounded-full border border-border bg-surface-2 px-2.5 py-1 text-xs font-medium text-muted-foreground sm:flex">
								<span
									className={`h-1.5 w-1.5 rounded-full ${status?.players !== undefined ? "bg-success" : "bg-destructive"}`}
								/>
								{status.players} player{status.players === 1 ? "" : "s"}
							</span>
						)}
						<div className="flex items-center gap-2 text-sm font-medium">
							<div
								className={`h-2 w-2 rounded-full ${isSystemOnline ? "bg-success" : "bg-destructive"}`}
							/>
							<span className="hidden text-muted-foreground md:inline">
								{isSystemOnline ? "System Online" : "System Offline"}
							</span>
						</div>
						{who?.user && (
							<div className="flex items-center gap-4 border-l border-border pl-4 lg:gap-6 lg:pl-6">
								<span className="hidden text-sm font-medium sm:inline">
									OP: {who.user}
								</span>
								<button
									type="button"
									onClick={handleSignOut}
									className="flex items-center gap-2 rounded-md text-sm font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
									title="Sign out"
								>
									<LogOut size={16} />
									<span className="hidden md:inline">Sign out</span>
								</button>
							</div>
						)}
					</div>
				</div>
			</header>

			<div className="flex flex-1">
				{/* Mobile drawer */}
				{navOpen && (
					<button
						type="button"
						aria-label="Close navigation"
						onClick={handleNav}
						className="fixed inset-0 z-30 cursor-default bg-black/40 lg:hidden"
					/>
				)}
				<aside
					className={`fixed bottom-0 left-0 top-16 z-40 w-64 shrink-0 border-r border-border bg-card transition-transform lg:sticky lg:top-16 lg:z-auto lg:h-[calc(100vh-4rem)] lg:translate-x-0 lg:overflow-y-auto lg:transition-none ${navOpen ? "translate-x-0" : "-translate-x-full"}`}
				>
					{nav}
				</aside>

				<main className="min-w-0 flex-1 px-4 py-6 sm:px-6 lg:px-8 xl:px-12">
					{children}
				</main>
			</div>
		</div>
	);
}
