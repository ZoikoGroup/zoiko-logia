"use client";

import { useEffect, useState } from "react";
import { MessageSquare } from "lucide-react";
import { Card } from "@/components/governance/Card";
import { getAuthToken, listSavedAnswers, type SavedAnswer } from "@/lib/api";
import type { RoleCode } from "@/lib/roles";

export const allowedRoles: RoleCode[] = [
  "CFO", "Controller", "Audit Partner", "Tax Director", "Finance Manager",
  "Business Owner", "Learner", "AI Governance Lead", "Admin",
];

export function RecentKritonActivityModule() {
  const [recent, setRecent] = useState<SavedAnswer[]>([]);

  useEffect(() => {
    listSavedAnswers(getAuthToken())
      .then((rows) => setRecent(rows.slice(0, 2)))
      .catch(() => setRecent([]));
  }, []);

  return (
    <Card title="Recent Kriton Activity">
      {recent.length === 0 ? (
        <p className="text-xs text-muted">No saved answers yet — questions you save from Ask Kriton appear here.</p>
      ) : (
        <div className="space-y-3">
          {recent.map((item) => (
            <div key={item.id} className="flex items-start gap-2.5">
              <MessageSquare size={15} className="text-brand mt-0.5 shrink-0" />
              <div>
                <div className="text-sm text-ink">{item.query_text}</div>
                <div className="text-[11px] text-muted">{new Date(item.created_at).toLocaleString()}</div>
              </div>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
