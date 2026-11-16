/** Approval workflows: the standalone JSON flows (platform admins), and a repository's choice. */

import { api } from "./http";

export interface StepBrief {
  id: string;
  name: string;
  type: string; // a registered step type, e.g. "DOCUMENT_REVIEW"
}

export interface WorkflowSummary {
  id: string;
  code: string; // e.g. "DOC_HUB.DOCUMENT_APPROVAL"
  name: string;
  kind: string; // what its steps work on, e.g. "DOC_HUB.DOCUMENT"
  kind_label: string; // e.g. "Document"
  latest_version: number;
  last_published_at: string | null;
  steps: StepBrief[]; // the latest version's
  used_by: number; // nodes (e.g. repositories) using it
}

export interface WorkflowVersion {
  id: string;
  version: number;
  status: string;
  published_at: string | null;
  definition: Flow;
}

export interface Workflow extends WorkflowSummary {
  versions: WorkflowVersion[]; // newest first
  used_by_nodes: string[];
}

/** The JSON flow (see backend app/workflows/flow.py). */
export interface Flow {
  code: string;
  name?: string;
  start: string;
  steps: FlowStep[];
}

export interface FlowStep {
  id: string;
  type: string;
  name: string;
  role?: { user_group: string; role: string };
  completion?: { rule: string };
  on: Record<string, string>;
}

export interface StepType {
  code: string;
  kind: string;
  kind_label: string;
  outcomes: string[];
  description: string;
}

/** A repository's workflow: what new submissions use, and what it can switch to. */
export interface WorkflowChoice {
  id: string;
  code: string;
  name: string;
  version: number;
  steps: { id: string; name: string; type: string; user_group: string | null; role: string | null; on: Record<string, string> }[];
}

export interface RepoWorkflow {
  current: WorkflowChoice | null;
  options: WorkflowChoice[];
  missing_groups: string[]; // user groups the current workflow names that the repository doesn't have
}

const json = (body: unknown) => JSON.stringify(body);

export const listWorkflows = (t: string) => api<WorkflowSummary[]>(t, "/approval-workflows");
export const getWorkflow = (t: string, id: string) => api<Workflow>(t, `/approval-workflows/${id}`);
export const listStepTypes = (t: string) => api<StepType[]>(t, "/approval-workflows/step-types");
export const validateFlow = (t: string, definition: unknown) =>
  api<{ ok: boolean; steps: number; start: string; kind: string }>(t, "/approval-workflows/validate", {
    method: "POST",
    body: json({ definition }),
  });
export const createWorkflow = (t: string, definition: unknown) =>
  api<Workflow>(t, "/approval-workflows", { method: "POST", body: json({ definition }) });
export const publishVersion = (t: string, id: string, definition: unknown) =>
  api<WorkflowVersion>(t, `/approval-workflows/${id}/versions`, { method: "POST", body: json({ definition }) });

export const getRepoWorkflow = (t: string, repoId: string) => api<RepoWorkflow>(t, `/doc-repos/${repoId}/workflow`);
export const setRepoWorkflow = (t: string, repoId: string, workflowId: string) =>
  api<RepoWorkflow>(t, `/doc-repos/${repoId}/workflow`, { method: "PUT", body: json({ workflow_id: workflowId }) });
