"use client";

import { useState } from "react";
import { useAudit } from "@/lib/api";
import {
	Card,
	CardContent,
	CardHeader,
	CardDescription,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Select } from "@/components/ui/select";
import {
	Table,
	TableBody,
	TableCell,
	TableHead,
	TableHeader,
	TableRow,
} from "@/components/ui/table";
import { History } from "lucide-react";

type AuditEntry = {
	id: number;
	ts: number;
	username: string;
	action: string;
	target?: string | null;
	detail?: unknown;
};

function methodBadge(action: string) {
	const method = action.split(" ")[0];
	if (method === "DELETE") return <Badge variant="danger">DELETE</Badge>;
	if (method === "POST") return <Badge variant="success">POST</Badge>;
	if (method === "PUT" || method === "PATCH")
		return <Badge variant="warn">{method}</Badge>;
	return <Badge variant="neutral">{method}</Badge>;
}

export default function AuditPage() {
	const [limit, setLimit] = useState(100);
	const { data, mutate } = useAudit(limit);
	const entries: AuditEntry[] = data?.entries ?? [];

	return (
		<div className="space-y-5">
			<div className="flex flex-wrap items-end justify-between gap-3">
				<div>
					<h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
						<History className="h-5 w-5" /> Audit Log
					</h1>
					<p className="text-sm text-muted-foreground">
						Every mutating admin action, newest first. Read-only and
						append-only.
					</p>
				</div>
				<div className="flex items-center gap-2">
					<Select
						value={String(limit)}
						onChange={(e) => setLimit(Number(e.target.value))}
						className="w-36"
					>
						<option value="50">50 rows</option>
						<option value="100">100 rows</option>
						<option value="250">250 rows</option>
						<option value="500">500 rows</option>
					</Select>
					<Button
						variant="outline"
						size="sm"
						onClick={() => {
							void mutate();
						}}
					>
						Refresh
					</Button>
				</div>
			</div>

			<Card>
				<CardHeader>
					<div>
						<CardDescription>{entries.length} entries.</CardDescription>
					</div>
				</CardHeader>
				<CardContent className="p-0">
					<Table compact>
						<TableHeader>
							<TableRow>
								<TableHead className="w-40">Time</TableHead>
								<TableHead>Operator</TableHead>
								<TableHead className="w-20">Method</TableHead>
								<TableHead>Action</TableHead>
								<TableHead>Target</TableHead>
								<TableHead className="w-24">Result</TableHead>
							</TableRow>
						</TableHeader>
						<TableBody>
							{entries.map((e) => {
								const status = (e.detail as { status?: number } | null)?.status;
								return (
									<TableRow key={e.id}>
										<TableCell className="tnum whitespace-nowrap text-muted-foreground">
											{new Date(e.ts * 1000).toLocaleString()}
										</TableCell>
										<TableCell className="font-medium">{e.username}</TableCell>
										<TableCell>{methodBadge(e.action)}</TableCell>
										<TableCell className="max-w-[22rem] truncate font-mono text-xs">
											{e.action}
										</TableCell>
										<TableCell className="max-w-[14rem] truncate font-mono text-xs text-muted-foreground">
											{e.target ?? "-"}
										</TableCell>
										<TableCell>
											{status !== undefined ? (
												<Badge
													variant={status < 400 ? "neutral" : "danger"}
													className="tnum"
												>
													{status}
												</Badge>
											) : (
												"-"
											)}
										</TableCell>
									</TableRow>
								);
							})}
							{entries.length === 0 && (
								<TableRow>
									<TableCell
										colSpan={6}
										className="py-12 text-center text-muted-foreground"
									>
										No admin actions recorded yet.
									</TableCell>
								</TableRow>
							)}
						</TableBody>
					</Table>
				</CardContent>
			</Card>
		</div>
	);
}
