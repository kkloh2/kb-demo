import { useCallback } from "react";
import { listAudit, type AuditFilters } from "../../api/audit";
import { AuditTrail } from "./AuditTrail";
import "../../styles/knowledge-bases.css";
import "../../styles/admin.css";
import "../../styles/kb-detail.css";
import "../../styles/doc-repos.css";

interface Props {
  token: string;
  onSessionEnded: (message: string) => void;
}

/** Platform admins: the whole audit trail, newest first, with filters. */
export function AuditPage({ token, onSessionEnded }: Props) {
  const fetchPage = useCallback((f: AuditFilters) => listAudit(token, f), [token]);
  return (
    <div className="page">
      <h1 className="page__title">Audit</h1>
      <AuditTrail fetchPage={fetchPage} everywhere onSessionEnded={onSessionEnded} />
    </div>
  );
}
