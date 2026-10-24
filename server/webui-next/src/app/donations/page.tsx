"use client";

import { useState } from "react";
import { HandHeart, Plus, Ticket } from "lucide-react";
import { runMutation, useDonations } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";

type Donation = {
	id: number;
	loginId: string;
	note: string;
	created: number;
	creditedAt: number | null;
	creditedBy: string | null;
	creditedTickets: number | null;
};

export default function DonationsPage() {
	const { data, isLoading, error, mutate } = useDonations();
	const [counts, setCounts] = useState<Record<number, string>>({});
	const [loginId, setLoginId] = useState("");
	const [count, setCount] = useState("1");
	const [reason, setReason] = useState("");
	const [busy, setBusy] = useState(false);
	const donations = (data?.entries || []) as Donation[];

	const creditDonation = async (donation: Donation) => {
		setBusy(true);
		try {
			await runMutation(
				`/api/donations/${donation.id}/credit`,
				{
					method: "POST",
					body: JSON.stringify({ count: Number(counts[donation.id] || 1) }),
				},
				"Donation credited with tickets",
			);
			await mutate();
		} finally {
			setBusy(false);
		}
	};
	const topup = async () => {
		setBusy(true);
		try {
			await runMutation(
				"/api/player-portal/tickets",
				{
					method: "POST",
					body: JSON.stringify({ loginId, count: Number(count), reason }),
				},
				"Tickets added",
			);
			setLoginId("");
			setCount("1");
			setReason("");
		} finally {
			setBusy(false);
		}
	};

	return (
		<div className="space-y-5">
			<div>
				<h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
					<HandHeart className="h-5 w-5" /> Donations
				</h1>
				<p className="text-sm text-muted-foreground">
					Transfer notes never credit automatically. Only an operator can grant
					tickets.
				</p>
			</div>

			<Card>
				<CardHeader>
					<div>
						<CardTitle className="flex items-center gap-2">
							<Plus className="h-4 w-4 text-muted-foreground" /> Manual ticket
							top-up
						</CardTitle>
						<CardDescription>
							For an account without a donation note. The reason is shown in its
							ticket history.
						</CardDescription>
					</div>
				</CardHeader>
				<CardContent className="grid gap-3 sm:grid-cols-[1.2fr_.5fr_1fr_auto] sm:items-end">
					<label
						htmlFor="topup-login"
						className="grid gap-1 text-xs font-medium text-muted-foreground"
					>
						Login ID
						<Input
							id="topup-login"
							value={loginId}
							onChange={(e) => setLoginId(e.target.value)}
							placeholder="google_… or Guest_…"
						/>
					</label>
					<label
						htmlFor="topup-count"
						className="grid gap-1 text-xs font-medium text-muted-foreground"
					>
						Tickets
						<Input
							id="topup-count"
							type="number"
							min="1"
							value={count}
							onChange={(e) => setCount(e.target.value)}
						/>
					</label>
					<label
						htmlFor="topup-reason"
						className="grid gap-1 text-xs font-medium text-muted-foreground"
					>
						Reason
						<Input
							id="topup-reason"
							value={reason}
							onChange={(e) => setReason(e.target.value)}
							placeholder="Event thank-you"
						/>
					</label>
					<Button
						disabled={busy || !loginId || !count || !reason}
						onClick={topup}
					>
						<Ticket className="mr-1 h-4 w-4" />
						Add
					</Button>
				</CardContent>
			</Card>

			{error && (
				<p className="text-sm text-destructive">
					Could not load donations: {error.message}
				</p>
			)}
			<div className="grid gap-4">
				{isLoading && (
					<Card>
						<CardContent className="py-8 text-sm text-muted-foreground">
							Loading donations…
						</CardContent>
					</Card>
				)}
				{!isLoading && !donations.length && (
					<Card>
						<CardContent className="py-8 text-sm text-muted-foreground">
							No donation notes yet.
						</CardContent>
					</Card>
				)}
				{donations.map((donation) => (
					<Card key={donation.id}>
						<CardHeader>
							<div className="min-w-0">
								<CardTitle className="text-base">{donation.loginId}</CardTitle>
								<CardDescription className="font-mono text-[11px]">
									#{donation.id} ·{" "}
									{new Date(donation.created * 1000).toLocaleString()}
								</CardDescription>
							</div>
							{donation.creditedAt ? (
								<Badge variant="success">
									Credited {donation.creditedTickets} ticket(s)
								</Badge>
							) : (
								<Badge variant="warn">Awaiting review</Badge>
							)}
						</CardHeader>
						<CardContent className="space-y-3 pt-3">
							<p className="whitespace-pre-wrap text-sm leading-6">
								{donation.note}
							</p>
							{donation.creditedAt ? (
								<p className="text-xs text-muted-foreground">
									Credited by {donation.creditedBy || "operator"} ·{" "}
									{new Date(donation.creditedAt * 1000).toLocaleString()}
								</p>
							) : (
								<div className="flex flex-wrap items-end gap-2">
									<label
										htmlFor={`gift-${donation.id}`}
										className="grid gap-1 text-xs font-medium text-muted-foreground"
									>
										Gift tickets
										<Input
											id={`gift-${donation.id}`}
											className="w-28"
											type="number"
											min="1"
											value={counts[donation.id] || "1"}
											onChange={(e) =>
												setCounts((current) => ({
													...current,
													[donation.id]: e.target.value,
												}))
											}
										/>
									</label>
									<Button
										disabled={busy}
										onClick={() => creditDonation(donation)}
									>
										<HandHeart className="mr-1 h-4 w-4" />
										Credit manually
									</Button>
								</div>
							)}
						</CardContent>
					</Card>
				))}
			</div>
		</div>
	);
}
