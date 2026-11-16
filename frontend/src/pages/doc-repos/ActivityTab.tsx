import { useCallback } from "react";
import { nodeActivity, type AuditFilters } from "../../api/audit";
import type { DocRepo } from "../../api/doc-repos";
import { AuditTrail } from "../audit/AuditTrail";

interface Props {
  token: string;
  docRepo: DocRepo;
  onSessionEnded: (message: string) => void;
}

/** Owner, admins and auditors: everything that happened in this repository, laid out like the Audit page. */
export function ActivityTab({ token, docRepo, onSessionEnded }: Props) {
  const fetchPage = useCallback(
    ({ source_system: _, ...f }: AuditFilters) => nodeActivity(token, docRepo.node_id, f),
    [token, docRepo.node_id],
  );
  return <AuditTrail fetchPage={fetchPage} onSessionEnded={onSessionEnded} />;
}
